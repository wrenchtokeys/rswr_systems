"""
Invoice Storage Service for RS Systems

Saves generated invoices to S3 for:
- Record keeping
- Audit trail
- Re-downloading later

Author: Amelia (Clawdbot AI)
Created: 2026-01-27
"""

import os
import json
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, asdict

import boto3
from botocore.exceptions import ClientError
from django.utils import timezone

from apps.clawdbot.services.invoice_service import InvoiceData


# S3 path structure: invoices/{customer_id}/{year}/{invoice_number}.pdf
S3_INVOICE_PREFIX = "invoices"


@dataclass
class StoredInvoice:
    """Metadata for a stored invoice"""
    invoice_number: str
    customer_id: int
    customer_name: str
    total: float
    item_count: int
    s3_key: str
    created_at: str
    file_size: int


class InvoiceStorageService:
    """
    Service for storing and retrieving invoices from S3.
    
    Usage:
        service = InvoiceStorageService()
        
        # Save an invoice
        s3_key = service.save_invoice(pdf_bytes, invoice_data, customer_id)
        
        # List invoices for a customer
        invoices = service.list_customer_invoices(customer_id)
        
        # Get an invoice
        pdf_bytes = service.get_invoice(s3_key)
    """
    
    def __init__(self):
        self._setup_s3_client()
    
    def _setup_s3_client(self):
        """Initialize S3 client"""
        self.s3_client = None
        self.s3_bucket = None
        
        try:
            aws_key = os.environ.get('AWS_ACCESS_KEY_ID')
            aws_secret = os.environ.get('AWS_SECRET_ACCESS_KEY')
            self.s3_bucket = os.environ.get('AWS_STORAGE_BUCKET_NAME')
            region = os.environ.get('AWS_S3_REGION_NAME', 'us-east-1')
            
            if aws_key and aws_secret and self.s3_bucket:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=aws_key,
                    aws_secret_access_key=aws_secret,
                    region_name=region
                )
        except Exception as e:
            print(f"Warning: Could not initialize S3 client: {e}")
    
    def _generate_s3_key(self, customer_id: int, invoice_number: str) -> str:
        """Generate S3 key for an invoice"""
        year = timezone.now().year
        return f"{S3_INVOICE_PREFIX}/{customer_id}/{year}/{invoice_number}.pdf"
    
    def _generate_metadata_key(self, customer_id: int, invoice_number: str) -> str:
        """Generate S3 key for invoice metadata"""
        year = timezone.now().year
        return f"{S3_INVOICE_PREFIX}/{customer_id}/{year}/{invoice_number}_metadata.json"
    
    def save_invoice(
        self,
        pdf_bytes: bytes,
        invoice_data: InvoiceData,
        customer_id: int
    ) -> Tuple[bool, str]:
        """
        Save an invoice PDF to S3.
        
        Args:
            pdf_bytes: The PDF file content
            invoice_data: Invoice metadata
            customer_id: Customer ID
            
        Returns:
            Tuple of (success: bool, s3_key or error message)
        """
        if not self.s3_client:
            return False, "S3 client not configured"
        
        try:
            # Generate S3 keys
            pdf_key = self._generate_s3_key(customer_id, invoice_data.invoice_number)
            metadata_key = self._generate_metadata_key(customer_id, invoice_data.invoice_number)
            
            # Upload PDF
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=pdf_key,
                Body=pdf_bytes,
                ContentType='application/pdf',
                Metadata={
                    'invoice_number': invoice_data.invoice_number,
                    'customer_name': invoice_data.customer_name,
                    'total': str(invoice_data.total),
                }
            )
            
            # Upload metadata JSON
            metadata = StoredInvoice(
                invoice_number=invoice_data.invoice_number,
                customer_id=customer_id,
                customer_name=invoice_data.customer_name,
                total=float(invoice_data.total),
                item_count=len(invoice_data.line_items),
                s3_key=pdf_key,
                created_at=timezone.now().isoformat(),
                file_size=len(pdf_bytes)
            )
            
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=metadata_key,
                Body=json.dumps(asdict(metadata)),
                ContentType='application/json'
            )
            
            return True, pdf_key
            
        except ClientError as e:
            return False, f"S3 error: {str(e)}"
        except Exception as e:
            return False, f"Error saving invoice: {str(e)}"
    
    def get_invoice(self, s3_key: str) -> Optional[bytes]:
        """
        Retrieve an invoice PDF from S3.
        
        Args:
            s3_key: The S3 key of the invoice
            
        Returns:
            PDF bytes or None if not found
        """
        if not self.s3_client:
            return None
        
        try:
            response = self.s3_client.get_object(Bucket=self.s3_bucket, Key=s3_key)
            return response['Body'].read()
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                return None
            raise
    
    def list_customer_invoices(
        self,
        customer_id: int,
        year: Optional[int] = None,
        limit: int = 50
    ) -> List[StoredInvoice]:
        """
        List all stored invoices for a customer.
        
        Args:
            customer_id: Customer ID to list invoices for
            year: Optional year filter (defaults to all years)
            limit: Maximum number of invoices to return
            
        Returns:
            List of StoredInvoice objects
        """
        if not self.s3_client:
            return []
        
        try:
            # Build prefix
            if year:
                prefix = f"{S3_INVOICE_PREFIX}/{customer_id}/{year}/"
            else:
                prefix = f"{S3_INVOICE_PREFIX}/{customer_id}/"
            
            # List objects
            response = self.s3_client.list_objects_v2(
                Bucket=self.s3_bucket,
                Prefix=prefix,
                MaxKeys=limit * 2  # Account for metadata files
            )
            
            invoices = []
            if 'Contents' in response:
                for obj in response['Contents']:
                    # Only process metadata files
                    if obj['Key'].endswith('_metadata.json'):
                        try:
                            meta_response = self.s3_client.get_object(
                                Bucket=self.s3_bucket,
                                Key=obj['Key']
                            )
                            meta_data = json.loads(meta_response['Body'].read())
                            invoices.append(StoredInvoice(**meta_data))
                        except Exception as e:
                            print(f"Error reading metadata {obj['Key']}: {e}")
            
            # Sort by created_at descending
            invoices.sort(key=lambda x: x.created_at, reverse=True)
            
            return invoices[:limit]
            
        except ClientError as e:
            print(f"Error listing invoices: {e}")
            return []
    
    def get_invoice_url(self, s3_key: str, expires_in: int = 3600) -> Optional[str]:
        """
        Generate a pre-signed URL for downloading an invoice.
        
        Args:
            s3_key: The S3 key of the invoice
            expires_in: URL expiration time in seconds (default 1 hour)
            
        Returns:
            Pre-signed URL or None
        """
        if not self.s3_client:
            return None
        
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.s3_bucket,
                    'Key': s3_key
                },
                ExpiresIn=expires_in
            )
            return url
        except ClientError as e:
            print(f"Error generating URL: {e}")
            return None


# Convenience functions
def save_invoice_to_s3(pdf_bytes: bytes, invoice_data: InvoiceData, customer_id: int) -> Tuple[bool, str]:
    """Save an invoice to S3"""
    service = InvoiceStorageService()
    return service.save_invoice(pdf_bytes, invoice_data, customer_id)


def get_customer_invoices(customer_id: int, limit: int = 50) -> List[StoredInvoice]:
    """List invoices for a customer"""
    service = InvoiceStorageService()
    return service.list_customer_invoices(customer_id, limit=limit)

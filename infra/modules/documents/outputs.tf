output "bucket_name" {
  description = "Bucket name — the application's S3_BUCKET setting."
  value       = aws_s3_bucket.this.id
}

output "bucket_arn" {
  description = "Bucket ARN — scopes the task roles' object permissions."
  value       = aws_s3_bucket.this.arn
}

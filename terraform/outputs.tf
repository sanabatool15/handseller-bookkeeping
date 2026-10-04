output "cloudfront_url" {
  description = "Public URL of the app"
  value       = "https://${aws_cloudfront_distribution.main.domain_name}"
}

output "inngest_url" {
  description = "URL to register in Inngest Cloud"
  value       = "https://${aws_cloudfront_distribution.main.domain_name}/api/inngest"
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.main.id
}

output "api_gateway_url" {
  value = aws_apigatewayv2_api.main.api_endpoint
}

output "s3_frontend_bucket" {
  value = aws_s3_bucket.frontend.id
}

output "lambda_function_name" {
  value = aws_lambda_function.api.function_name
}

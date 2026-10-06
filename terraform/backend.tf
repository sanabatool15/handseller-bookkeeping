terraform {
  # Bucket, key and region are passed by scripts/deploy.* and destroy.* via -backend-config
  backend "s3" {}
}

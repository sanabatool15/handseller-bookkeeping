# Non-secret production overrides (secrets go in secrets.prod.tfvars, git-ignored)
lambda_memory            = 1024
lambda_timeout           = 30
api_throttle_burst_limit = 100
api_throttle_rate_limit  = 50

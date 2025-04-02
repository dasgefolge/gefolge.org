#!/usr/bin/env pwsh

cargo sqlx prepare --workspace -- -p gefolge-web -p gefolge-web-lib -p gefolge-web-back -p gefolge-paypal
if (-not $?)
{
    throw 'Native Failure'
}

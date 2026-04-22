#!/bin/sh
set -e

awslocal sesv2 create-email-identity --email-identity alerts@elasnocongresso.local || true

awslocal sesv2 create-email-identity --email-identity newsletter@elasnocongresso.local || true

echo "SES identities created"
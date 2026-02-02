#!/bin/bash
# deploy_cloud_gateway.sh

echo "Creating directory structure..."
mkdir -p config

echo "Creating configuration..."
cat > config/cloud_accounts.json << 'EOF'
{
  "accounts": [
    {
      "name": "ollama-account-1",
      "api_key": "REPLACE_WITH_YOUR_API_KEY_1",
      "description": "Primary account"
    },
    {
      "name": "ollama-account-2",
      "api_key": "REPLACE_WITH_YOUR_API_KEY_2",
      "description": "Backup account 1"
    },
    {
      "name": "ollama-account-3",
      "api_key": "REPLACE_WITH_YOUR_API_KEY_3",
      "description": "Backup account 2"
    }
  ]
}
EOF

echo "Please edit config/cloud_accounts.json and add your actual Ollama Cloud API keys"
echo "Then run: sudo docker-compose up -d"
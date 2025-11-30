# Telegram Configuration Template
# Copy this file to config_secret.py and fill in your actual credentials
# NEVER commit config_secret.py to git!

# Instructions:
# 1. Copy this file: cp config_secret.template.py config_secret.py
# 2. Edit config_secret.py with your actual credentials
# 3. Verify config_secret.py is in .gitignore

# Get your Telegram Bot Token from @BotFather on Telegram
TELEGRAM_BOT_TOKEN = 'YOUR_BOT_TOKEN_HERE'

# Get your Chat ID by messaging your bot and checking:
# https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates
TELEGRAM_CHAT_ID = 'YOUR_CHAT_ID_HERE'

# SEC requires a User-Agent header with your email for API access
# Use your real email address
SEC_USER_AGENT = 'your.email@example.com'

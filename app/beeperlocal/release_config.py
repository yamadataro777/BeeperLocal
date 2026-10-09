"""Public release settings. Never put client secrets or signing keys here."""
# Set to the published, PKCE-enabled Slack application's public client ID.
SLACK_CLIENT_ID = "11683442969584.12190221092304"
SLACK_REDIRECT_URI = "beeperlocal://oauth/slack"
# Set only after verifying PKCE, redirect/scopes and distribution in Slack settings.
SLACK_DISTRIBUTION_READY = True

"""Public build metadata only. No credential store, database or network access."""
import re
from . import release_config


def release_status():
    client = release_config.SLACK_CLIENT_ID
    configured = (isinstance(client, str) and bool(re.fullmatch(r'[0-9]{1,32}\.[0-9]{1,32}', client))
                  and release_config.SLACK_REDIRECT_URI == 'beeperlocal://oauth/slack')
    return {'slackOAuthConfigured': configured,
            'slackClientId': client if configured else '',
            'slackRedirectUri': release_config.SLACK_REDIRECT_URI if configured else '',
            'slackDistributionReady': configured and release_config.SLACK_DISTRIBUTION_READY is True}

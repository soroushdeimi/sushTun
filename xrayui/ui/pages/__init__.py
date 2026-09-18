"""macOS-style page widgets for the sidebar window."""
from .activity_page import ActivityPage
from .servers_page import ServersPage
from .subscriptions_page import SidebarSubscriptionList, SubscriptionsPage

__all__ = [
    "ActivityPage",
    "ServersPage",
    "SidebarSubscriptionList",
    "SubscriptionsPage",
]

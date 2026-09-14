"""macOS-style page widgets for the sidebar window.

The coordinator merges both worker branches' exports in this file by hand.
"""
from .activity_page import ActivityPage
from .servers_page import ServersPage
from .subscriptions_page import SidebarSubscriptionList, SubscriptionsPage

__all__ = [
    "ActivityPage",
    "ServersPage",
    "SidebarSubscriptionList",
    "SubscriptionsPage",
]

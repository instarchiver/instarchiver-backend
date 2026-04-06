"""Django Unfold Admin Configuration.

This module contains all configuration settings for the Django Unfold admin interface.
For more information about available options, see:
https://unfoldadmin.com/docs/configuration/settings/
"""

UNFOLD = {
    "SITE_TITLE": "Instarchiver Admin",
    "SITE_HEADER": "Instarchiver",
    "SITE_URL": "/",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "STYLES": [
        lambda request: "css/admin-custom.css",
    ],
    "SCRIPTS": [],
    "COLORS": {
        "primary": {
            "50": "250 245 255",
            "100": "243 232 255",
            "200": "233 213 255",
            "300": "216 180 254",
            "400": "196 141 252",
            "500": "168 85 247",
            "600": "147 51 234",
            "700": "126 34 206",
            "800": "107 33 168",
            "900": "88 28 135",
            "950": "59 7 100",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
        "navigation": [
            {
                "title": "Navigation",
                "separator": True,
                "items": [
                    {
                        "title": "Dashboard",
                        "icon": "dashboard",
                        "link": "/admin/",
                    },
                ],
            },
            {
                "title": "User Management",
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": "Users",
                        "icon": "people",
                        "link": "/admin/users/user/",
                    },
                    {
                        "title": "Groups",
                        "icon": "group",
                        "link": "/admin/auth/group/",
                    },
                ],
            },
            {
                "title": "Celery Beat",
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": "Periodic Tasks",
                        "icon": "schedule",
                        "link": "/admin/django_celery_beat/periodictask/",
                    },
                    {
                        "title": "Crontab Schedule",
                        "icon": "access_time",
                        "link": "/admin/django_celery_beat/crontabschedule/",
                    },
                    {
                        "title": "Interval Schedule",
                        "icon": "timer",
                        "link": "/admin/django_celery_beat/intervalschedule/",
                    },
                    {
                        "title": "Clocked Schedule",
                        "icon": "alarm",
                        "link": "/admin/django_celery_beat/clockedschedule/",
                    },
                ],
            },
            {
                "title": "Celery Results",
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": "Task Results",
                        "icon": "assignment_turned_in",
                        "link": "/admin/django_celery_results/taskresult/",
                    },
                    {
                        "title": "Group Results",
                        "icon": "group_work",
                        "link": "/admin/django_celery_results/groupresult/",
                    },
                ],
            },
            {
                "title": "Instagram",
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": "Users",
                        "icon": "account_circle",
                        "link": "/admin/instagram/user/",
                    },
                    {
                        "title": "Posts",
                        "icon": "collections",
                        "link": "/admin/instagram/post/",
                    },
                    {
                        "title": "Post Media",
                        "icon": "perm_media",
                        "link": "/admin/instagram/postmedia/",
                    },
                    {
                        "title": "Stories",
                        "icon": "photo_library",
                        "link": "/admin/instagram/story/",
                    },
                    {
                        "title": "Story Update Logs",
                        "icon": "history",
                        "link": "/admin/instagram/userupdatestorylog/",
                    },
                    {
                        "title": "Story Credit",
                        "icon": "history",
                        "link": "/admin/instagram/storycredit/",
                    },
                    {
                        "title": "Story Credit Logs",
                        "icon": "history",
                        "link": "/admin/instagram/storycreditpayment/",
                    },
                    {
                        "title": "User Follows",
                        "icon": "people",
                        "link": "/admin/instagram/userfollow/",
                    },
                ],
            },
            {
                "title": "Payments",
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": "Pricing Plans",
                        "icon": "local_offer",
                        "link": "/admin/payments/pricingplan/",
                    },
                    {
                        "title": "Payments",
                        "icon": "payment",
                        "link": "/admin/payments/payment/",
                    },
                    {
                        "title": "Webhook Logs",
                        "icon": "history",
                        "link": "/admin/payments/webhooklog/",
                    },
                    {
                        "title": "Gateway Options",
                        "icon": "history",
                        "link": "/admin/payments/gatewayoption/",
                    },
                    {
                        "title": "Payment Settings",
                        "icon": "history",
                        "link": "/admin/payments/paymentsetting/",
                    },
                ],
            },
            {
                "title": "API Monitoring",
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": "API Request Logs",
                        "icon": "history",
                        "link": "/admin/api_logs/apirequestlog/",
                    },
                ],
            },
            {
                "title": "Settings",
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": "OpenAI Settings",
                        "icon": "smart_toy",
                        "link": "/admin/settings/openaisetting/",
                    },
                    {
                        "title": "Core API Settings",
                        "icon": "api",
                        "link": "/admin/settings/coreapisetting/",
                    },
                    {
                        "title": "Firebase Admin Settings",
                        "icon": "cloud",
                        "link": "/admin/settings/firebaseadminsetting/",
                    },
                    {
                        "title": "Stripe Settings",
                        "icon": "credit_card",
                        "link": "/admin/settings/stripesetting/",
                    },
                ],
            },
        ],
    },
}

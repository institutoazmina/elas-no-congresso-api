from django.utils import timezone
from unfold.decorators import admin_view


class DashboardStats:
    @staticmethod
    @admin_view
    def get_stats(request):
        from apps.legislatures.models import ParliamentarianTerm
        from apps.propositions.models import Proposition
        from apps.subscriptions.models import Subscription

        today = timezone.now().date()
        start_of_day = timezone.make_aware(
            timezone.datetime.combine(today, timezone.datetime.min.time())
        )

        total_propositions = Proposition.objects.count()
        propositions_this_year = Proposition.objects.filter(year=today.year).count()

        current_terms = ParliamentarianTerm.objects.filter(end_date__isnull=True)
        current_parliamentarians = (
            current_terms.values("parliamentarian").distinct().count()
        )

        active_subscriptions = Subscription.objects.filter(is_active=True).count()
        subscriptions_today = Subscription.objects.filter(
            confirmed_at__gte=start_of_day
        ).count()

        alerts_today = 0

        return {
            "total_propositions": total_propositions,
            "propositions_this_year": propositions_this_year,
            "current_parliamentarians": current_parliamentarians,
            "active_subscriptions": active_subscriptions,
            "subscriptions_today": subscriptions_today,
            "alerts_today": alerts_today,
        }


def get_admin_index_context(request):
    stats = DashboardStats.get_stats(request)
    return {
        "dashboard_stats": stats,
    }

from users.models import UserBadge

def award_badge(user, language, level, score, hints):
    """
    Awards badges based on level completion.
    Only Advanced level can award LEGEND badge.
    """
    # Always award badge for completing THIS level
    UserBadge.objects.get_or_create(
        user=user,
        language=language,
        level=level
    )

    # Legend Badge rule
    if level == "Advanced" and score >= 85 and hints < 2:
        UserBadge.objects.get_or_create(
            user=user,
            language=language,
            level="Legend"
        )
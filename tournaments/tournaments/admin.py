from django.contrib import admin
from django.urls import reverse
from django.utils.safestring import mark_safe

from . import models


@admin.register(models.Participant)
class ParticipantAdmin(admin.ModelAdmin):

    list_display = ('name', 'user')

    ordering = ('name',)


class ParticipationInline(admin.TabularInline):
    model = models.Participation
    fields = ('participant', 'slot_id', 'podium_position')

@admin.action(description='Reset active/finished tournament to open')
def reset_tournament(modeladmin, request, queryset):
    for tournament in queryset.all():
        if tournament.state not in ('active', 'finished'):
            continue
        for participation in tournament.participations.all():
            participation.podium_position = None
            participation.save()
        for stage in tournament.stages.all():
            stage.fixtures.all().delete()
        assert tournament.state == 'open'


@admin.register(models.Tournament)
class TournamentAdmin(admin.ModelAdmin):

    list_display = ('name', 'published', 'state', 'creator', 'entry_fee', 'platform_fee_percent', 'effective_prize')
    list_filter  = ('published', 'creator')

    actions = [reset_tournament]

    fieldsets = (
        (None, {
            'fields': (
                'name',
                'definition',
                'podium_spec',
                'published',
                'creator',
                'starts_at',
                'min_players',
                'max_players',
                'target_points',
                'time_control',
                'doubling_enabled',
                'entry_fee',
                'platform_fee_percent',
                'prize_money')
            }
        ),
    )

    inlines = [
        ParticipationInline,
    ]

    def state(self, obj):
        return obj.state

    @admin.display(description='Prize pool')
    def effective_prize(self, obj):
        return obj.effective_prize_money

    ordering = ('name',)


@admin.register(models.Fixture)
class FixtureAdmin(admin.ModelAdmin):

    list_display = ('id', 'tournament', 'mode', 'level', 'extras', 'player1', 'player2', 'score')
    list_filter  = ('mode__tournament',)

    ordering = ('mode__tournament', 'mode', 'level')

    def tournament(self, fixture):
        url = reverse('admin:tournaments_tournament_change', args=(fixture.mode.tournament.pk,))
        return mark_safe(f'<a href="{ url }">{ fixture.mode.tournament.name }</a>')

    def score(self, fixture):
        return f'{fixture.score[0]}:{fixture.score[1]}' if fixture.score else '-'


@admin.register(models.WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):

    list_display = ('created_at', 'user', 'kind', 'amount', 'balance_after', 'tournament', 'head_to_head_table', 'actor')
    list_filter = ('kind', 'created_at')
    search_fields = ('user__username', 'actor__username', 'tournament__name', 'note')
    readonly_fields = ('created_at', 'balance_after')
    ordering = ('-created_at', '-id')


@admin.register(models.DirectPlaySettings)
class DirectPlaySettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Availability', {'fields': ('enabled',)}),
        ('Format profiles', {'fields': ('format_profiles',)}),
        ('Legacy play with a friend', {
            'fields': ('friend_game_fee',),
            'description': 'Fixed fee charged to each player for the entire game, regardless of target points. No percentage or winner prize applies.',
        }),
        ('Platform fees', {'fields': ('head_to_head_fee_percent', 'tournament_fee_percent', 'stake_amounts')}),
        ('Game rules', {'fields': ('game_rules',)}),
        ('Recurring coin bonus', {'fields': ('coin_grant_enabled', 'coin_grant_amount', 'coin_grant_interval_hours')}),
    )
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        return not models.DirectPlaySettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.HeadToHeadTable)
class HeadToHeadTableAdmin(admin.ModelAdmin):
    list_display = ('code', 'mode', 'is_quick_match', 'host', 'guest', 'amount', 'fee_per_player', 'time_control', 'doubling_enabled', 'status', 'created_at')
    list_filter = ('mode', 'is_quick_match', 'status', 'time_control', 'doubling_enabled', 'created_at')
    search_fields = ('code', 'host__username', 'guest__username', 'external_room_id')
    readonly_fields = ('code', 'host', 'guest', 'winner', 'amount', 'fee_percent', 'fee_per_player', 'game_format', 'rules_snapshot', 'settlement', 'created_at', 'updated_at', 'completed_at')
    ordering = ('-created_at',)

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

    list_display = ('name', 'published', 'state', 'creator', 'entry_fee', 'prize_money')
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
                'prize_money')
            }
        ),
    )

    inlines = [
        ParticipationInline,
    ]

    def state(self, obj):
        return obj.state

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

    list_display = ('created_at', 'user', 'kind', 'amount', 'balance_after', 'tournament', 'actor')
    list_filter = ('kind', 'created_at')
    search_fields = ('user__username', 'actor__username', 'tournament__name', 'note')
    readonly_fields = ('created_at', 'balance_after')
    ordering = ('-created_at', '-id')

from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path('', views.DashboardView.as_view(), name='dashboard'),
    path('tournaments/', views.IndexView.as_view(), name='index'),
    path('t/create', views.CreateTournamentView.as_view(),
         name='create-tournament'),
    path('t/update/<int:pk>', views.UpdateTournamentView.as_view(),
         name='update-tournament'),
    path('t/publish/<int:pk>', views.PublishTournamentView.as_view(),
         name='publish-tournament'),
    path('t/draft/<int:pk>', views.DraftTournamentView.as_view(),
         name='draft-tournament'),
    path('t/delete/<int:pk>', views.DeleteTournamentView.as_view(),
         name='delete-tournament'),
    path('t/join/<int:pk>', views.JoinTournamentView.as_view(),
         name='join-tournament'),
    path('t/withdraw/<int:pk>', views.WithdrawTournamentView.as_view(),
         name='withdraw-tournament'),
    path('t/progress/<int:pk>', views.TournamentProgressView.as_view(),
         name='tournament-progress'),
    path('t/clone/<int:pk>', views.CloneTournamentView.as_view(),
         name='clone-tournament'),
    path('t/participants/<int:pk>',
         views.ManageParticipantsView.as_view(), name='manage-participants'),

    # --- Admin: User management (staff-only) ---
    path('users/', views.UserListView.as_view(), name='user-list'),
    path('users/create', views.UserCreateView.as_view(), name='user-create'),
    path('users/<int:pk>/edit', views.UserUpdateView.as_view(), name='user-edit'),
    path('users/<int:pk>/delete', views.UserDeleteView.as_view(), name='user-delete'),
    path('accounts/login/',
         LoginView.as_view(template_name='frontend/login.html'), name='login'),
    #     path('accounts/signup/', views.SignupView.as_view(), name='signup'),
    path('accounts/logout/', LogoutView.as_view(), name='logout'),




]

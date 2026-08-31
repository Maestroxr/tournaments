# Admin Panel Design — 2026-08-31

## Context
- Existing app: `tournaments` (Django 4.2) with `frontend` (server-rendered Bootstrap 4) + `api.py` (JSON API for separate Vite/Vue user frontend at `/api/`).
- User wants to convert current `frontend` templates/views from public tournament UI to staff-only admin panel. Admin must create tournaments and manage users (full CRUD). Vue app remains user-facing via API.

## Decision
- Approach 1: Minimal Wrap — add `AdminRequiredMixin` to existing management views, add user management views, keep `api.py` untouched. Mounted at `/`, API at `/api/`. Separate URL separation: Vite app talks to `/api/`, admin uses `/` HTML.

## Architecture
- App stays `frontend`. New `AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin)` where `test_func = is_staff or is_superuser`.
- `tournaments/urls.py` unchanged: `path('', include('frontend.urls'))` is admin, `path('api/', include('frontend.api_urls'))` is user API, `path('admin/', admin.site.urls)` remains.
- Auth: single `auth.User` with `is_staff` flag. Non-staff API login allowed, but `/` returns 403. Anonymous -> 302 to `/accounts/login/`.
- Disable public `SignupView` / `api/auth/signup` optionally (admin creates users). Keep `LoginView`/`LogoutView`.

## Components

### Mixins & Views (`frontend/views.py`)
- `AdminRequiredMixin`
- `IsCreatorAndAdminMixin` (IsCreator + AdminRequired)
- Update: `IndexView`, `CreateTournamentView`, `UpdateTournamentView`, `PublishTournamentView`, `DraftTournamentView`, `DeleteTournamentView`, `ManageParticipantsView`, `CloneTournamentView`, `TournamentProgressView` (GET open->403 for non-creator staff check kept) to inherit `AdminRequiredMixin`.
- New file `frontend/views_users.py` or in `views.py`:
  - `UserListView(AdminRequiredMixin, ListView)` model User, paginate 20, `?q` search, template `frontend/user_list.html`.
  - `UserCreateView(AdminRequiredMixin, FormView)` form `AdminUserCreateForm`, template `frontend/user_form.html`, success -> `user-list`.
  - `UserUpdateView(AdminRequiredMixin, UpdateView)` model User, form `AdminUserUpdateForm`, blocks editing username to reserved `testuser-*`.
  - `UserDeleteView(AdminRequiredMixin, DeleteView)` blocks self-delete.

### Forms (`frontend/forms.py`)
- `AdminUserCreateForm(UserCreationForm)` + `is_staff` BooleanField, `email` optional. Reuse `clean_username` reserve check.
- `AdminUserUpdateForm(forms.ModelForm)` fields: username, email, is_staff, optional new password (PasswordInput). Validates same reserve.

### URLs (`frontend/urls.py`)
```py
path('users/', UserListView, name='user-list')
path('users/create', UserCreateView, name='user-create')
path('users/<int:pk>/edit', UserUpdateView, name='user-edit')
path('users/<int:pk>/delete', UserDeleteView, name='user-delete')
# remove/disable: path('accounts/signup/', SignupView)
```

### Templates
- `base.html`: nav adds `{% if user.is_staff %}` Tournaments | Users | Create Tournament, staff badge, admin prefix in title.
- `user_list.html`: table id, username, email, is_staff, is_active, actions edit/delete, search bar, create button.
- `user_form.html`: crispy form, password1/2, is_staff checkbox.
- `user_confirm_delete.html`: confirm.
- `index.html`: admin dashboard header "Admin — Tournaments", counts, same tournament-list includes.

### Models
- No model changes. Reuse `auth.User` and `tournaments.Tournament`.

## Data Flow
- Admin POST tournament YAML -> `CreateTournamentForm.validate_definition` -> `Tournament.load` -> `definition` stored -> `published` flag controls API visibility (`api_tournaments` filters published=True).
- Admin POST users -> `User.objects.create_user` -> Vue user can `POST /api/auth/login` with same credentials.
- Participant linking via `Participant.get_or_create_for_user` on join.

## Permissions & Errors
- 302 to login if anonymous, 403 if authenticated non-staff (UserPassesTestMixin).
- State errors keep 412 (draft vs open). Self-delete 403 or form error.
- Messages via `request.session['alert']` kept.

## Testing
- Update `frontend/tests.py`: use `is_staff=True` for existing tournament tests, add `test_non_staff_forbidden` for 403.
- New `UserManagementTests`: staff can list/create/edit/delete, non-staff 403, delete-self blocked, reserved username blocked.
- API tests unchanged.

## Out of Scope
- No new app, no SPA for admin, no RBAC beyond is_staff, no email verification, no pagination beyond 20.

## Verification
- `python manage.py test` passes, `python manage.py check`, manual: staff login -> / shows dashboard, /users/ works; non-staff login -> 403 on /; Vue API login/join still works.

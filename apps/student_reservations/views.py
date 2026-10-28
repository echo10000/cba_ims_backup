from datetime import timedelta
from django.db import models
from django.views import View
from django.views.generic import ListView, DetailView
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from django.contrib import messages

from apps.inventory.models import Asset, AssetCategory
from .models import StudentReservation
from .forms import PublicStudentReservationForm
from . import services
from .security import mask_contact_info


class CustodianRequiredMixin(LoginRequiredMixin):
    """
    Enforces Administrator / Property Custodian authorization for student reservation office actions.
    Non-custodian users (Faculty, Students, Chairs, Deans) are denied access.
    """
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        is_admin = getattr(request.user, 'is_admin', False) or getattr(request.user, 'role', '') == 'ADMIN'
        if not is_admin:
            raise PermissionDenied("You do not have administrative authority to manage student equipment reservations.")
        return super().dispatch(request, *args, **kwargs)


# ==============================================================================
# PUBLIC STUDENT VIEWS — NO LOGIN REQUIRED
# ==============================================================================

def get_sensible_default_schedule():
    """
    Computes a sensible default pickup and return schedule during active office hours in Asia/Manila.
    - Considers weekdays (Monday=0 to Friday=4).
    - If today is a weekend, suggests next Monday morning session (8:00 AM - 12:00 PM).
    - If weekday before 8:00 AM: suggests today 8:00 AM - 12:00 PM.
    - If weekday 8:00 AM - 12:00 PM: suggests today 1:00 PM - 5:00 PM.
    - If weekday 12:00 PM - 3:00 PM: suggests today (next round hour) to 5:00 PM.
    - If weekday after 3:00 PM: suggests next weekday 8:00 AM - 12:00 PM.
    """
    now = timezone.localtime()
    weekday = now.weekday()  # 0=Mon, ..., 6=Sun
    hour = now.hour

    if weekday in (5, 6):  # Saturday or Sunday -> suggest next Monday
        days_ahead = 7 - weekday
        target_date = (now + timedelta(days=days_ahead)).date()
        pickup = timezone.make_aware(timezone.datetime.combine(target_date, timezone.datetime.min.time().replace(hour=8)))
        ret = timezone.make_aware(timezone.datetime.combine(target_date, timezone.datetime.min.time().replace(hour=12)))
    else:  # Monday to Friday
        if hour < 8:
            pickup = now.replace(hour=8, minute=0, second=0, microsecond=0)
            ret = now.replace(hour=12, minute=0, second=0, microsecond=0)
        elif 8 <= hour < 12:
            pickup = now.replace(hour=13, minute=0, second=0, microsecond=0)
            ret = now.replace(hour=17, minute=0, second=0, microsecond=0)
        elif 12 <= hour < 15:
            pickup = (now + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
            ret = now.replace(hour=17, minute=0, second=0, microsecond=0)
        else:  # After 3:00 PM -> suggest next weekday
            days_ahead = 3 if weekday == 4 else 1  # Jump to Monday if Friday
            target_date = (now + timedelta(days=days_ahead)).date()
            pickup = timezone.make_aware(timezone.datetime.combine(target_date, timezone.datetime.min.time().replace(hour=8)))
            ret = timezone.make_aware(timezone.datetime.combine(target_date, timezone.datetime.min.time().replace(hour=12)))

    return pickup, ret


def _build_catalog_cards(categories, pickup_dt, return_dt):
    """Builds unified category cards reflecting inventory and availability for selected schedule."""
    catalog_cards = []
    for cat in categories:
        tot_assets = services.get_reservable_assets(category=cat)
        total_count = tot_assets.count()
        avail_assets = services.get_available_assets_for_category(cat, pickup_dt, return_dt)
        avail_count = len(avail_assets)

        models_list = list(tot_assets.exclude(model='').values_list('model', flat=True).distinct()[:3])
        models_preview = ", ".join(models_list) if models_list else (
            "Standard CBA Instructional Inventory" if total_count > 0 else "No units registered in service"
        )

        # Build equipment types breakdown under this category
        equipment_types_data = []
        active_types = cat.equipment_types.filter(is_active=True).order_by('name')
        for eq_type in active_types:
            type_assets = tot_assets.filter(equipment_type=eq_type)
            type_total = type_assets.count()
            type_avail = len(services.get_available_assets_for_category(
                cat, pickup_dt, return_dt, equipment_type_ref=eq_type
            ))
            t_name_lower = eq_type.name.lower()
            if 'projector' in t_name_lower:
                illustration = '/static/images/student/projector_lcd.svg'
            elif 'mic' in t_name_lower or 'sound' in t_name_lower or 'audio' in t_name_lower:
                illustration = '/static/images/student/wireless_mic.svg'
            else:
                illustration = '/static/images/student/equipment_generic.svg'

            equipment_types_data.append({
                'id': eq_type.id,
                'name': eq_type.name,
                'total_units': type_total,
                'available_units': type_avail,
                'is_available': type_avail > 0,
                'illustration_url': illustration,
            })

        asset_with_img = tot_assets.filter(asset_image__isnull=False).exclude(asset_image='').first()
        sample_image_url = asset_with_img.asset_image.url if asset_with_img and asset_with_img.asset_image else None

        cat_name_lower = cat.name.lower()
        if 'projector' in cat_name_lower or 'av' in cat.code.lower() or 'audio-visual' in cat_name_lower:
            icon = 'bi bi-projector'
            cat_illustration = '/static/images/student/projector_lcd.svg'
        elif 'speaker' in cat_name_lower or 'sound' in cat_name_lower or 'audio' in cat_name_lower or 'mic' in cat_name_lower:
            icon = 'bi bi-speaker'
            cat_illustration = '/static/images/student/wireless_mic.svg'
        elif 'laptop' in cat_name_lower or 'it' in cat.code.lower() or 'computer' in cat_name_lower:
            icon = 'bi bi-laptop'
            cat_illustration = '/static/images/student/equipment_generic.svg'
        elif 'display' in cat_name_lower or 'monitor' in cat_name_lower or 'screen' in cat_name_lower:
            icon = 'bi bi-display'
            cat_illustration = '/static/images/student/equipment_generic.svg'
        elif 'cable' in cat_name_lower or 'adapter' in cat_name_lower or 'accessories' in cat_name_lower or 'clicker' in cat_name_lower:
            icon = 'bi bi-plug'
            cat_illustration = '/static/images/student/equipment_generic.svg'
        else:
            icon = 'bi bi-box-seam'
            cat_illustration = '/static/images/student/equipment_generic.svg'

        catalog_cards.append({
            'category': cat,
            'total_units': total_count,
            'available_units': avail_count,
            'is_zero_stock': total_count == 0,
            'is_fully_booked': total_count > 0 and avail_count == 0,
            'is_available': avail_count > 0,
            'models_preview': models_preview,
            'equipment_types': equipment_types_data,
            'sample_image_url': sample_image_url,
            'illustration_url': sample_image_url or cat_illustration,
            'icon': icon,
        })
    return catalog_cards


def _is_projector_card(card):
    cat = card.get('category')
    name = (cat.name or '').lower() if cat else ''
    code = (cat.code or '').upper() if cat else ''
    if 'projector' in name or code in ('PRJ', 'PROJ'):
        return True
    for eq_type in card.get('equipment_types', []):
        if 'projector' in eq_type.get('name', '').lower():
            return True
    return False


def _partition_catalog_cards(catalog_cards):
    """
    Partitions catalog items into:
    1. featured_projector: The primary Projectors category (prominent full-width card).
    2. secondary_available_cards: Other available equipment categories (e.g. microphones).
    3. unavailable_cards: Fully booked or zero-stock equipment categories (placed in disclosure).
    """
    featured_projector = None
    secondary_available_cards = []
    unavailable_cards = []

    for card in catalog_cards:
        if _is_projector_card(card) and featured_projector is None:
            eq_types = card.get('equipment_types', [])
            avail_types = [t for t in eq_types if t.get('is_available')]
            card['primary_type'] = avail_types[0] if avail_types else (eq_types[0] if eq_types else None)
            card['has_multiple_types'] = len(eq_types) > 1
            featured_projector = card
            continue

        if card.get('available_units', 0) > 0 and not card.get('is_zero_stock', False):
            secondary_available_cards.append(card)
        else:
            unavailable_cards.append(card)

    return featured_projector, secondary_available_cards, unavailable_cards


# ==============================================================================
# PUBLIC STUDENT VIEWS — NO LOGIN REQUIRED
# ==============================================================================

class StudentCatalogView(View):
    """
    Public equipment catalog screen for students.
    Displays single unified browse grid with schedule-based availability, stock indicators,
    sensible Asia/Manila office-hour presets, and clear reservation CTAs.
    """
    def get(self, request, *args, **kwargs):
        categories = services.get_reservable_categories()

        default_pickup, default_return = get_sensible_default_schedule()
        default_pickup_str = default_pickup.strftime('%Y-%m-%dT%H:%M')
        default_return_str = default_return.strftime('%Y-%m-%dT%H:%M')

        catalog_cards = _build_catalog_cards(categories, default_pickup, default_return)
        featured_projector, secondary_available_cards, unavailable_cards = _partition_catalog_cards(catalog_cards)
        if featured_projector:
            catalog_cards = [featured_projector] + secondary_available_cards + unavailable_cards
        duration_hours = round((default_return - default_pickup).total_seconds() / 3600, 1)

        # Backwards-compatible availability_data list
        availability_data = [
            {
                'category': c['category'],
                'total_count': c['total_units'],
                'available_count': c['available_units'],
                'sample_models': c['models_preview'],
            }
            for c in catalog_cards
        ]

        context = {
            'categories': categories,
            'catalog_cards': catalog_cards,
            'featured_projector': featured_projector,
            'secondary_available_cards': secondary_available_cards,
            'unavailable_cards': unavailable_cards,
            'default_pickup': default_pickup_str,
            'default_return': default_return_str,
            'pickup_display': default_pickup.strftime('%b %d, %Y — %I:%M %p'),
            'return_display': default_return.strftime('%b %d, %Y — %I:%M %p'),
            'pickup_raw': default_pickup_str,
            'return_raw': default_return_str,
            'duration_hours': duration_hours,
            'availability_data': availability_data,
        }
        return render(request, 'student_reservations/catalog.html', context)


class CheckAvailabilityView(View):
    """
    HTMX endpoint for dynamic schedule-based availability checking.
    Calculates available units for each reservable category within [pickup, return].
    """
    def get(self, request, *args, **kwargs):
        pickup_str = request.GET.get('pickup', '').strip()
        return_str = request.GET.get('return', '').strip()

        if not pickup_str or not return_str:
            return render(request, 'student_reservations/partials/_availability_result.html', {
                'error': "Please select both pickup and return date and time."
            })

        try:
            current_tz = timezone.get_current_timezone()
            pickup = timezone.datetime.fromisoformat(pickup_str)
            return_dt = timezone.datetime.fromisoformat(return_str)

            if timezone.is_naive(pickup):
                pickup = timezone.make_aware(pickup, current_tz)
            if timezone.is_naive(return_dt):
                return_dt = timezone.make_aware(return_dt, current_tz)
        except (ValueError, TypeError):
            return render(request, 'student_reservations/partials/_availability_result.html', {
                'error': "Invalid date and time format. Please select valid dates."
            })

        if pickup >= return_dt:
            return render(request, 'student_reservations/partials/_availability_result.html', {
                'error': "Requested return time must be strictly after pickup time."
            })

        now = timezone.now()
        if pickup < now - timedelta(minutes=15):
            return render(request, 'student_reservations/partials/_availability_result.html', {
                'error': "Requested pickup time cannot be in the past."
            })

        categories = services.get_reservable_categories()
        catalog_cards = _build_catalog_cards(categories, pickup, return_dt)
        featured_projector, secondary_available_cards, unavailable_cards = _partition_catalog_cards(catalog_cards)
        if featured_projector:
            catalog_cards = [featured_projector] + secondary_available_cards + unavailable_cards
        duration_hours = round((return_dt - pickup).total_seconds() / 3600, 1)

        availability_data = [
            {
                'category': c['category'],
                'total_count': c['total_units'],
                'available_count': c['available_units'],
                'sample_models': c['models_preview'],
            }
            for c in catalog_cards
        ]

        context = {
            'error': None,
            'pickup_display': pickup.strftime('%b %d, %Y — %I:%M %p'),
            'return_display': return_dt.strftime('%b %d, %Y — %I:%M %p'),
            'pickup_raw': pickup_str,
            'return_raw': return_str,
            'duration_hours': duration_hours,
            'catalog_cards': catalog_cards,
            'featured_projector': featured_projector,
            'secondary_available_cards': secondary_available_cards,
            'unavailable_cards': unavailable_cards,
            'availability_data': availability_data,
        }
        return render(request, 'student_reservations/partials/_availability_result.html', context)


class PublicReservationSubmitView(View):
    """
    Public student reservation submission view and endpoint.
    GET: Renders mobile-friendly reservation form with optional prefilled category/dates/equipment-type.
    POST: Validates form, checks rate limiting, calls submit_reservation, and redirects to confirmation.
    Also maintains JSON API responses for programmatic requests.
    """
    @staticmethod
    def _get_category_types_data():
        from apps.inventory.models import EquipmentType
        all_types = EquipmentType.objects.filter(
            is_active=True,
            category__is_active=True,
            category__is_reservable=True
        ).values('id', 'name', 'category_id').order_by('name')

        mapping = {}
        for t in all_types:
            cid = str(t['category_id'])
            if cid not in mapping:
                mapping[cid] = []
            mapping[cid].append({'id': t['id'], 'name': t['name']})
        return mapping

    @classmethod
    def _get_category_types_json(cls):
        import json
        return json.dumps(cls._get_category_types_data())

    @staticmethod
    def _build_selection_context(cat, eq_type, pickup_val, return_val):
        """
        Builds display metadata for the prefilled selection summary card.
        Only marks selection_prefilled=True when required details are present and valid.
        """
        if not cat:
            return False, {}

        pickup_dt = None
        ret_dt = None
        current_tz = timezone.get_current_timezone()

        if isinstance(pickup_val, str) and pickup_val:
            try:
                pickup_dt = timezone.datetime.fromisoformat(pickup_val)
                if timezone.is_naive(pickup_dt):
                    pickup_dt = timezone.make_aware(pickup_dt, current_tz)
            except Exception:
                pass
        elif hasattr(pickup_val, 'strftime'):
            pickup_dt = pickup_val

        if isinstance(return_val, str) and return_val:
            try:
                ret_dt = timezone.datetime.fromisoformat(return_val)
                if timezone.is_naive(ret_dt):
                    ret_dt = timezone.make_aware(ret_dt, current_tz)
            except Exception:
                pass
        elif hasattr(return_val, 'strftime'):
            ret_dt = return_val

        has_types = cat.equipment_types.filter(is_active=True).exists()
        type_required_and_missing = has_types and not eq_type

        is_valid_schedule = pickup_dt and ret_dt and pickup_dt < ret_dt
        is_prefilled = bool(cat and not type_required_and_missing and is_valid_schedule)

        display_name = eq_type.name if eq_type else cat.name
        name_lower = display_name.lower()
        if 'projector' in name_lower:
            illustration = '/static/images/student/projector_lcd.svg'
        elif 'mic' in name_lower or 'sound' in name_lower or 'audio' in name_lower:
            illustration = '/static/images/student/wireless_mic.svg'
        else:
            illustration = '/static/images/student/equipment_generic.svg'

        duration = round((ret_dt - pickup_dt).total_seconds() / 3600, 1) if (pickup_dt and ret_dt) else None

        selection_display = {
            'category_name': cat.name,
            'category_id': cat.id,
            'type_name': display_name,
            'type_id': eq_type.id if eq_type else '',
            'has_type': bool(eq_type),
            'pickup': pickup_dt.strftime('%b %d, %Y · %I:%M %p') if pickup_dt else (pickup_val or ''),
            'return': ret_dt.strftime('%b %d, %Y · %I:%M %p') if ret_dt else (return_val or ''),
            'pickup_raw': str(pickup_val or ''),
            'return_raw': str(return_val or ''),
            'duration_hours': duration,
            'illustration_url': illustration,
        }
        return is_prefilled, selection_display

    def get(self, request, *args, **kwargs):
        initial_data = {}
        cat = None
        category_id = request.GET.get('category')
        if category_id:
            try:
                if str(category_id).isdigit():
                    cat = AssetCategory.objects.get(pk=int(category_id), is_active=True, is_reservable=True)
                else:
                    cat = AssetCategory.objects.filter(code__iexact=str(category_id).strip(), is_active=True, is_reservable=True).first()
                if cat:
                    initial_data['category'] = cat.pk
            except Exception:
                pass

        eq_type = None
        type_id = request.GET.get('type') or request.GET.get('equipment_type_id') or request.GET.get('equipment_type')
        if type_id:
            try:
                from apps.inventory.models import EquipmentType
                if str(type_id).isdigit():
                    eq_type = EquipmentType.objects.select_related('category').get(pk=int(type_id), is_active=True)
                else:
                    eq_type = EquipmentType.objects.select_related('category').filter(name__iexact=str(type_id).strip(), is_active=True).first()
                if eq_type and eq_type.category.is_active and eq_type.category.is_reservable:
                    initial_data['equipment_type_ref'] = eq_type.pk
                    if 'category' not in initial_data:
                        initial_data['category'] = eq_type.category.pk
                        cat = eq_type.category
            except Exception:
                pass

        pickup = request.GET.get('pickup')
        if pickup:
            initial_data['requested_pickup'] = pickup

        ret = request.GET.get('return')
        if ret:
            initial_data['requested_return'] = ret

        purpose_param = request.GET.get('purpose')
        if purpose_param:
            initial_data['purpose'] = purpose_param

        venue_param = request.GET.get('room_venue') or request.GET.get('venue')
        if venue_param:
            initial_data['room_venue'] = venue_param

        selection_prefilled, selection_display = self._build_selection_context(
            cat, eq_type, pickup, ret
        )

        form = PublicStudentReservationForm(initial=initial_data)
        category_types_data = self._get_category_types_data()
        return render(request, 'student_reservations/reservation_form.html', {
            'form': form,
            'category_types_data': category_types_data,
            'category_types_json': self._get_category_types_json(),
            'selection_prefilled': selection_prefilled,
            'selection_display': selection_display,
        })

    def post(self, request, *args, **kwargs):
        is_json_request = (
            request.content_type == 'application/json' or
            request.headers.get('accept') == 'application/json' or
            request.headers.get('x-requested-with') == 'XMLHttpRequest'
        )

        form = PublicStudentReservationForm(request.POST)
        if not form.is_valid():
            if is_json_request:
                return JsonResponse({
                    'success': False,
                    'errors': form.errors.get_json_data()
                }, status=400)
            category_types_data = self._get_category_types_data()
            cat = None
            eq_type = None
            cid = request.POST.get('category')
            if cid:
                try:
                    cat = AssetCategory.objects.get(pk=cid, is_active=True)
                except Exception:
                    pass
            tid = request.POST.get('equipment_type_ref')
            if tid:
                try:
                    from apps.inventory.models import EquipmentType
                    eq_type = EquipmentType.objects.get(pk=tid, is_active=True)
                except Exception:
                    pass
            _, selection_display = self._build_selection_context(
                cat, eq_type, request.POST.get('requested_pickup'), request.POST.get('requested_return')
            )
            return render(request, 'student_reservations/reservation_form.html', {
                'form': form,
                'category_types_data': category_types_data,
                'category_types_json': self._get_category_types_json(),
                'selection_prefilled': False,
                'selection_display': selection_display,
            })

        data = form.cleaned_data
        try:
            reservation = services.submit_reservation(
                student_id=data['student_id'],
                student_name=data['student_name'],
                course_year_section=data['course_year_section'],
                email=data['email'],
                contact_number=data['contact_number'],
                category=data['category'],
                requested_pickup=data['requested_pickup'],
                requested_return=data['requested_return'],
                purpose=data['purpose'],
                room_venue=data.get('room_venue', ''),
                equipment_type=data.get('equipment_type', ''),
                equipment_type_ref=data.get('equipment_type_ref'),
                remarks='',
                created_by=request.user if request.user.is_authenticated else None,
                request=request
            )

            if is_json_request:
                return JsonResponse({
                    'success': True,
                    'reservation_id': reservation.pk,
                    'lookup_token': reservation.lookup_token,
                    'status': reservation.status,
                    'equipment_type_ref': reservation.equipment_type_ref.name if reservation.equipment_type_ref else None,
                    'message': "Reservation submitted successfully. Please save your lookup token to track status."
                }, status=201)

            messages.success(
                request,
                "Your reservation request was submitted successfully! Please save your tracking token."
            )
            return redirect('student_reservations:public_confirmation', token=reservation.lookup_token)

        except ValidationError as e:
            if is_json_request:
                return JsonResponse({
                    'success': False,
                    'errors': e.message_dict if hasattr(e, 'message_dict') else {'__all__': [str(e)]}
                }, status=400)

            if hasattr(e, 'message_dict'):
                for field, error_list in e.message_dict.items():
                    for err in error_list:
                        form.add_error(field if field in form.fields else None, err)
            else:
                form.add_error(None, str(e.message if hasattr(e, 'message') else e))

            category_types_data = self._get_category_types_data()
            cat = None
            eq_type = None
            cid = request.POST.get('category')
            if cid:
                try:
                    cat = AssetCategory.objects.get(pk=cid, is_active=True)
                except Exception:
                    pass
            tid = request.POST.get('equipment_type_ref')
            if tid:
                try:
                    from apps.inventory.models import EquipmentType
                    eq_type = EquipmentType.objects.get(pk=tid, is_active=True)
                except Exception:
                    pass
            _, selection_display = self._build_selection_context(
                cat, eq_type, request.POST.get('requested_pickup'), request.POST.get('requested_return')
            )
            return render(request, 'student_reservations/reservation_form.html', {
                'form': form,
                'category_types_data': category_types_data,
                'category_types_json': self._get_category_types_json(),
                'selection_prefilled': False,
                'selection_display': selection_display,
            })


class PublicReservationConfirmationView(View):
    """
    Public confirmation screen rendered immediately after a successful reservation submission.
    Displays the secure tracking token with one-click copy, summary particulars, and institutional checklist.
    """
    def get(self, request, token, *args, **kwargs):
        try:
            reservation = services.get_reservation_by_token(token)
        except ValidationError:
            messages.error(request, "Reservation not found.")
            return redirect('student_reservations:public_lookup_search')

        return render(request, 'student_reservations/confirmation.html', {
            'reservation': reservation,
        })


class PublicReservationLookupView(View):
    """
    Public endpoint and interface for tracking reservation status via secure lookup token.
    Student ID is NEVER used as a lookup key to protect student privacy.
    Masks student contact information in response.
    Supports both HTML web pages and JSON API consumers.
    """
    def get(self, request, token=None, *args, **kwargs):
        is_json_request = (
            request.headers.get('accept') == 'application/json' or
            request.GET.get('format') == 'json'
        )

        lookup_token = token or request.GET.get('token', '').strip()

        # If no token provided in URL or GET params:
        if not lookup_token:
            if is_json_request:
                return JsonResponse({'success': False, 'error': 'Lookup token is required.'}, status=400)
            return render(request, 'student_reservations/lookup.html', {
                'reservation': None,
                'token': '',
                'error': None,
            })

        # Token was supplied: retrieve reservation
        try:
            reservation = services.get_reservation_by_token(lookup_token)
        except ValidationError as e:
            if is_json_request:
                return JsonResponse({'success': False, 'error': str(e)}, status=404)
            return render(request, 'student_reservations/lookup.html', {
                'reservation': None,
                'token': lookup_token,
                'error': str(e),
            })

        masked_email, masked_phone = mask_contact_info(reservation.email, reservation.contact_number)

        # JSON response handling
        if is_json_request:
            payload = {
                'success': True,
                'reservation_id': reservation.pk,
                'lookup_token': reservation.lookup_token,
                'status': reservation.status,
                'status_display': reservation.get_status_display(),
                'student_name': reservation.student_name,
                'course_year_section': reservation.course_year_section,
                'masked_email': masked_email,
                'masked_phone': masked_phone,
                'category_name': reservation.category.name,
                'equipment_type': reservation.equipment_type,
                'equipment_type_id': reservation.equipment_type_ref_id,
                'equipment_type_name': reservation.equipment_type_ref.name if reservation.equipment_type_ref else (reservation.equipment_type or None),
                'requested_pickup': reservation.requested_pickup.isoformat(),
                'requested_return': reservation.requested_return.isoformat(),
                'purpose': reservation.purpose,
                'room_venue': reservation.room_venue,
                'grace_period_minutes': reservation.grace_period_minutes,
                'pickup_deadline': reservation.pickup_deadline.isoformat() if reservation.pickup_deadline else None,
                'is_pickup_expired': reservation.is_pickup_expired,
                'is_overdue': reservation.is_overdue,
                'is_id_in_custody': reservation.is_id_in_custody,
                'allocated_asset': {
                    'asset_code': reservation.asset.asset_code,
                    'item_name': reservation.asset.item_name,
                } if reservation.asset else None,
                'created_at': reservation.created_at.isoformat(),
            }
            return JsonResponse(payload)

        # HTML response handling
        context = {
            'reservation': reservation,
            'masked_email': masked_email,
            'masked_phone': masked_phone,
            'token': lookup_token,
            'error': None,
        }

        # If HTMX request, render only the status card partial
        if request.headers.get('HX-Request'):
            return render(request, 'student_reservations/partials/_status_card.html', context)

        return render(request, 'student_reservations/lookup.html', context)


class EquipmentTypeLookupView(View):
    """
    Public JSON API endpoint returning active EquipmentTypes for a given category.
    GET /student-reservations/api/equipment-types/?category=<id>
    """
    def get(self, request, *args, **kwargs):
        from apps.inventory.models import EquipmentType
        category_id = request.GET.get('category')
        qs = EquipmentType.objects.filter(
            is_active=True,
            category__is_active=True,
            category__is_reservable=True
        ).order_by('name')

        if category_id:
            try:
                qs = qs.filter(category_id=int(category_id))
            except (ValueError, TypeError):
                return JsonResponse({'success': False, 'error': 'Invalid category ID.'}, status=400)

        data = [
            {
                'id': t.id,
                'name': t.name,
                'category_id': t.category_id,
                'category_name': t.category.name,
                'description': t.description,
            }
            for t in qs.select_related('category')
        ]
        return JsonResponse({'success': True, 'equipment_types': data})


# ==============================================================================
# CUSTODIAN BACKEND VIEWS (ADMINISTRATOR ONLY)
# ==============================================================================

class CustodianReservationListView(CustodianRequiredMixin, ListView):
    """
    Office management queue of student reservations for Property Custodians.
    """
    model = StudentReservation
    template_name = 'student_reservations/custodian_list.html'
    context_object_name = 'reservations'
    paginate_by = 25

    def get_queryset(self):
        services.auto_expire_uncollected_reservations()
        qs = StudentReservation.objects.select_related(
            'category', 'equipment_type_ref', 'asset', 'reviewed_by', 'released_by', 'returned_to'
        ).order_by('-created_at')

        status_filter = self.request.GET.get('status')
        if status_filter == 'OVERDUE':
            qs = qs.filter(status=StudentReservation.Status.RELEASED, requested_return__lt=timezone.now())
        elif status_filter:
            qs = qs.filter(status=status_filter)

        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                models.Q(student_id__icontains=q) |
                models.Q(student_name__icontains=q) |
                models.Q(lookup_token__icontains=q)
            )
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        base_qs = StudentReservation.objects.all()
        now = timezone.now()
        context['pending_count'] = base_qs.filter(status=StudentReservation.Status.PENDING).count()
        context['approved_count'] = base_qs.filter(status=StudentReservation.Status.APPROVED).count()
        context['released_count'] = base_qs.filter(status=StudentReservation.Status.RELEASED).count()
        context['overdue_count'] = base_qs.filter(status=StudentReservation.Status.RELEASED, requested_return__lt=now).count()
        context['awaiting_inspection_count'] = base_qs.filter(status=StudentReservation.Status.RETURNED_TO_GUARD).count()
        context['total_count'] = base_qs.count()
        context['current_status'] = self.request.GET.get('status', '')
        context['search_query'] = self.request.GET.get('q', '')
        return context


class CustodianReservationDetailView(CustodianRequiredMixin, DetailView):
    """
    Detail view of a specific student reservation for Custodian inspection and actions.
    Handles approval (with asset allocation), rejection, release, and return actions.
    """
    model = StudentReservation
    template_name = 'student_reservations/custodian_detail.html'
    context_object_name = 'reservation'

    def get_queryset(self):
        services.auto_expire_uncollected_reservations()
        return StudentReservation.objects.select_related(
            'category', 'equipment_type_ref', 'asset', 'reviewed_by', 'released_by', 'returned_to',
            'guard_recorded_by', 'cba_inspected_by', 'id_returned_by'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        res = self.object
        from .forms import (
            CustodianApprovalForm,
            CustodianRejectionForm,
            CustodianReleaseForm,
            CustodianOfficeReturnForm,
            CustodianGuardReturnForm,
            CustodianGuardInspectionForm,
            CustodianIDCollectionForm,
        )
        context['approval_form'] = CustodianApprovalForm(reservation=res)
        context['rejection_form'] = CustodianRejectionForm()
        context['release_form'] = CustodianReleaseForm()
        context['office_return_form'] = CustodianOfficeReturnForm()
        context['guard_return_form'] = CustodianGuardReturnForm()
        context['guard_inspection_form'] = CustodianGuardInspectionForm()
        context['id_collection_form'] = CustodianIDCollectionForm()
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        res = self.object
        action = request.POST.get('action')

        from .forms import (
            CustodianApprovalForm,
            CustodianRejectionForm,
            CustodianReleaseForm,
            CustodianOfficeReturnForm,
            CustodianGuardReturnForm,
            CustodianGuardInspectionForm,
            CustodianIDCollectionForm,
        )

        try:
            if action == 'approve':
                form = CustodianApprovalForm(res, request.POST)
                if form.is_valid():
                    asset = form.cleaned_data['asset']
                    grace = form.cleaned_data.get('grace_period_minutes', 15)
                    remarks = form.cleaned_data.get('remarks', '')
                    services.approve_reservation(
                        reservation=res,
                        asset=asset,
                        reviewed_by=request.user,
                        grace_period_minutes=grace,
                        remarks=remarks,
                        request=request
                    )
                    messages.success(request, f"Reservation #{res.pk} approved. Asset '{asset.asset_code}' ({asset.item_name}) allocated.")
                    return redirect('student_reservations:custodian_detail', pk=res.pk)
                else:
                    context = self.get_context_data()
                    context['approval_form'] = form
                    messages.error(request, "Failed to approve: please select a valid matching physical asset.")
                    return self.render_to_response(context)

            elif action == 'reject':
                form = CustodianRejectionForm(request.POST)
                if form.is_valid():
                    reason = form.cleaned_data['rejection_reason']
                    services.reject_reservation(
                        reservation=res,
                        reviewed_by=request.user,
                        rejection_reason=reason,
                        request=request
                    )
                    messages.warning(request, f"Reservation #{res.pk} rejected.")
                    return redirect('student_reservations:custodian_detail', pk=res.pk)
                else:
                    context = self.get_context_data()
                    context['rejection_form'] = form
                    messages.error(request, "Failed to reject: rejection reason is required.")
                    return self.render_to_response(context)

            elif action == 'release':
                form = CustodianReleaseForm(request.POST)
                if form.is_valid():
                    cond = form.cleaned_data['condition_at_release']
                    id_dep = form.cleaned_data.get('id_deposited', False)
                    remarks = form.cleaned_data.get('remarks', '')
                    services.release_equipment(
                        reservation=res,
                        released_by=request.user,
                        condition_at_release=cond,
                        id_deposited=id_dep,
                        remarks=remarks,
                        request=request
                    )
                    if getattr(res, 'is_projector', False):
                        msg = f"Projector allocated for reservation #{res.pk} marked as RELEASED to student."
                    else:
                        msg = f"Equipment for reservation #{res.pk} marked as RELEASED to student."
                    messages.success(request, msg)
                    return redirect('student_reservations:custodian_detail', pk=res.pk)
                else:
                    context = self.get_context_data()
                    context['release_form'] = form
                    first_err = form.errors.as_data()
                    if 'id_deposited' in first_err:
                        messages.error(request, "Failed to release: student ID must be deposited.")
                    else:
                        messages.error(request, "Failed to release: please correct the release form errors.")
                    return self.render_to_response(context)

            elif action == 'return_office':
                form = CustodianOfficeReturnForm(request.POST)
                if form.is_valid():
                    cond = form.cleaned_data['condition_at_return']
                    remarks = form.cleaned_data.get('return_remarks', '')
                    id_col = form.cleaned_data.get('id_collected_now', True)
                    services.return_equipment_to_office(
                        reservation=res,
                        returned_to=request.user,
                        condition_at_return=cond,
                        return_remarks=remarks,
                        id_collected_now=id_col,
                        request=request
                    )
                    messages.success(request, f"Reservation #{res.pk} completed and returned to CBA Property Office.")
                    return redirect('student_reservations:custodian_detail', pk=res.pk)
                else:
                    context = self.get_context_data()
                    context['office_return_form'] = form
                    messages.error(request, "Failed to record return: condition is required.")
                    return self.render_to_response(context)

            elif action == 'return_guard':
                form = CustodianGuardReturnForm(request.POST)
                if form.is_valid():
                    g_time = form.cleaned_data['guard_returned_at']
                    g_details = form.cleaned_data['guard_handover_details']
                    remarks = form.cleaned_data.get('remarks', '')
                    services.record_guard_return(
                        reservation=res,
                        recorded_by=request.user,
                        guard_returned_at=g_time,
                        guard_handover_details=g_details,
                        remarks=remarks,
                        request=request
                    )
                    messages.success(request, f"After-hours guard return logged for reservation #{res.pk}.")
                    return redirect('student_reservations:custodian_detail', pk=res.pk)
                else:
                    context = self.get_context_data()
                    context['guard_return_form'] = form
                    messages.error(request, "Failed to record guard handover.")
                    return self.render_to_response(context)

            elif action == 'inspect_guard':
                form = CustodianGuardInspectionForm(request.POST)
                if form.is_valid():
                    cond = form.cleaned_data['condition_at_return']
                    remarks = form.cleaned_data.get('inspection_remarks', '')
                    id_col = form.cleaned_data.get('id_collected_now', False)
                    services.complete_inspection(
                        reservation=res,
                        inspected_by=request.user,
                        condition_at_return=cond,
                        inspection_remarks=remarks,
                        id_collected_now=id_col,
                        request=request
                    )
                    if cond == Asset.Condition.UNSERVICEABLE:
                        messages.warning(request, f"Guard return inspection completed for reservation #{res.pk}. Asset marked UNSERVICEABLE (Damaged).")
                    else:
                        messages.success(request, f"Guard return inspection completed for reservation #{res.pk}. Asset restored to AVAILABLE.")
                    return redirect('student_reservations:custodian_detail', pk=res.pk)
                else:
                    context = self.get_context_data()
                    context['guard_inspection_form'] = form
                    messages.error(request, "Failed to complete inspection: please select a valid inspected condition.")
                    return self.render_to_response(context)

            elif action == 'collect_id':
                if res.status != StudentReservation.Status.RETURNED:
                    raise ValidationError("School ID collection can only be recorded after equipment return has been completed.")
                form = CustodianIDCollectionForm(request.POST)
                if form.is_valid():
                    remarks = form.cleaned_data.get('remarks', '')
                    services.record_id_collection(
                        reservation=res,
                        returned_by=request.user,
                        remarks=remarks,
                        request=request
                    )
                    messages.success(request, f"Physical School ID collection recorded for student {res.student_name} (#{res.pk}).")
                    return redirect('student_reservations:custodian_detail', pk=res.pk)
                else:
                    context = self.get_context_data()
                    context['id_collection_form'] = form
                    messages.error(request, "Failed to record School ID collection: confirmation is required.")
                    return self.render_to_response(context)

            else:
                messages.error(request, f"Unknown action: {action}")
                return redirect('student_reservations:custodian_detail', pk=res.pk)

        except ValidationError as e:
            messages.error(request, e.message if hasattr(e, 'message') else str(e))
            return redirect('student_reservations:custodian_detail', pk=res.pk)

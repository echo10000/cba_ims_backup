from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, FormView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Case, Count, F, IntegerField, OuterRef, ProtectedError, Q, Subquery, Value, When
from django.db.models.functions import Concat
from django.utils import timezone
from datetime import timedelta

from .models import AssetCategory, Brand, Asset, AssetVerification
from .forms import AssetCategoryForm, BrandForm, AssetForm, AssetUpdateForm, AssetVerificationForm, AssetCodeLookupForm
from . import qr_services
from apps.assignments.models import AssetAssignment
from apps.organizations.models import Department, Location
from apps.audit.utils import log_action


class InventoryAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Grants access to inventory views for ADMIN, DEAN, and DEPT_CHAIR.
    Ordinary FACULTY / staff are restricted in Phase 2.
    """
    def test_func(self):
        user = self.request.user
        if not user.is_authenticated:
            return False
        return (
            getattr(user, 'is_admin', False) or 
            getattr(user, 'role', '') in [user.Role.ADMIN, user.Role.DEAN, user.Role.DEPT_CHAIR]
        )


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restricts view exclusively to System Administrators / Property Custodians."""
    def test_func(self):
        return self.request.user.is_authenticated and getattr(self.request.user, 'is_admin', False)


# ==============================================================================
# ASSET VIEWS
# ==============================================================================

class AssetListView(InventoryAccessMixin, ListView):
    """
    Lists physical assets with search across 6 fields, multi-criteria filtering,
    role-based scoping, and pagination.
    """
    model = Asset
    template_name = 'inventory/asset_list.html'
    context_object_name = 'assets'
    paginate_by = 15

    def get_template_names(self):
        if (
            self.request.headers.get('HX-Request') == 'true'
            and self.request.headers.get('HX-History-Restore-Request') != 'true'
            and self.request.headers.get('HX-Boosted') != 'true'
        ):
            return ['inventory/partials/_asset_results.html']
        return [self.template_name]

    def get_queryset(self):
        qs = self._filtered_queryset()

        status = self.request.GET.get('status')
        if status:
            qs = qs.filter(status=status)
        elif not self.request.GET.get('show_disposed'):
            qs = qs.exclude(status=Asset.Status.DISPOSED)

        sort = self.request.GET.get('sort')
        if sort == 'item':
            qs = qs.order_by('item_name')
        elif sort == 'tag':
            qs = qs.order_by('asset_code')
        elif sort == 'need':
            qs = qs.annotate(
                needs_rank=Case(
                    When(status=Asset.Status.DAMAGED, then=Value(0)),
                    When(status=Asset.Status.LOST, then=Value(0)),
                    When(status=Asset.Status.MAINTENANCE, then=Value(1)),
                    When(status=Asset.Status.BORROWED, then=Value(2)),
                    default=Value(3),
                    output_field=IntegerField(),
                )
            ).order_by('needs_rank', 'asset_code')

        return qs

    def _filtered_queryset(self):
        """Scoped assets with search and every filter applied except status."""
        user = self.request.user
        open_assignments = AssetAssignment.objects.filter(returned_date__isnull=True)
        qs = Asset.objects.select_related(
            'category', 'brand', 'department', 'current_location', 'created_by'
        ).annotate(
            holder_name=Subquery(
                open_assignments.filter(asset=OuterRef('pk')).annotate(
                    holder=Concat(F('employee__first_name'), Value(' '), F('employee__last_name'))
                ).values('holder')[:1]
            )
        )

        # RBAC Scoping: Department Chairs only see assets in their assigned department
        if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'DEAN':
            pass
        elif getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(department=chair_dept)
            else:
                return qs.none()
        else:
            return qs.none()

        # Multi-field Search
        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(asset_code__icontains=q) |
                Q(property_number__icontains=q) |
                Q(item_name__icontains=q) |
                Q(serial_number__icontains=q) |
                Q(brand__name__icontains=q) |
                Q(model__icontains=q) |
                Q(current_location__name__icontains=q) |
                Q(department__name__icontains=q) |
                Q(holder_name__icontains=q)
            )

        # Combined Multi-Filter
        category = self.request.GET.get('category')
        brand = self.request.GET.get('brand')
        department = self.request.GET.get('department')
        location = self.request.GET.get('location')
        condition = self.request.GET.get('condition')

        if category:
            qs = qs.filter(category_id=category)
        if brand:
            qs = qs.filter(brand_id=brand)
        if department and not (getattr(user, 'role', '') == 'DEPT_CHAIR'):
            qs = qs.filter(department_id=department)
        if location:
            qs = qs.filter(current_location_id=location)
        if condition:
            qs = qs.filter(condition=condition)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        context['page_title'] = 'Physical Assets Inventory'
        context['categories'] = AssetCategory.objects.filter(is_active=True)
        context['brands'] = Brand.objects.filter(is_active=True)

        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            context['departments'] = Department.objects.filter(pk=chair_dept.pk) if chair_dept else Department.objects.none()
            context['locations'] = Location.objects.filter(department=chair_dept, is_active=True) if chair_dept else Location.objects.none()
        else:
            context['departments'] = Department.objects.filter(is_active=True)
            context['locations'] = Location.objects.filter(is_active=True)

        context['conditions'] = Asset.Condition.choices
        context['statuses'] = Asset.Status.choices

        params = self.request.GET
        current = {field: params.get(field, '') for field in ('q', 'status', 'category', 'department', 'location', 'condition', 'sort')}
        context.update({f'current_{field}': value for field, value in current.items()})

        counts = dict(
            self._filtered_queryset().values_list('status').annotate(total=Count('pk')).order_by()
        )
        shown = [
            (Asset.Status.AVAILABLE, 'Available'), (Asset.Status.BORROWED, 'On loan'),
            (Asset.Status.ASSIGNED, 'Assigned'), (Asset.Status.MAINTENANCE, 'In repair'),
            (Asset.Status.DAMAGED, 'Damaged'),
        ]
        total = sum(n for status, n in counts.items() if status != Asset.Status.DISPOSED)
        context['status_tabs'] = [{'value': '', 'label': 'All', 'count': total, 'active': not current['status']}] + [
            {'value': value, 'label': label, 'count': counts.get(value, 0), 'active': current['status'] == value}
            for value, label in shown
        ]

        def label_for(queryset, pk):
            return str(next((item for item in queryset if str(item.pk) == pk), pk))

        active = []
        if current['q']:
            active.append({'field': 'q', 'label': f'"{current["q"]}"'})
        if current['status']:
            active.append({'field': 'status', 'label': dict(Asset.Status.choices).get(current['status'], current['status'])})
        if current['department']:
            active.append({'field': 'department', 'label': label_for(context['departments'], current['department'])})
        if current['category']:
            active.append({'field': 'category', 'label': label_for(context['categories'], current['category'])})
        if current['condition']:
            active.append({'field': 'condition', 'label': dict(Asset.Condition.choices).get(current['condition'], current['condition'])})
        if current['location']:
            active.append({'field': 'location', 'label': label_for(context['locations'], current['location'])})
        context['active_filters'] = active

        # Build query parameters string for pagination links
        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()

        return context


class AssetDetailView(LoginRequiredMixin, DetailView):
    """
    Dedicated detail view for an asset by its unique asset_code.
    Enforces department scoping for Chairs and assigned-only access for Faculty.
    """
    model = Asset
    template_name = 'inventory/asset_detail.html'
    context_object_name = 'asset'
    slug_field = 'asset_code'
    slug_url_kwarg = 'asset_code'

    def get_queryset(self):
        return Asset.objects.select_related(
            'category', 'brand', 'department', 'current_location', 'created_by'
        )

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user

        # Admin & Dean can view any asset
        if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'DEAN':
            return obj

        # Department Chair: restricted to their department's assets
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if not chair_dept or obj.department != chair_dept:
                raise PermissionDenied("You do not have permission to view equipment outside your department.")
            return obj

        # Faculty / Staff: can only view if the asset is currently assigned or borrowed to them
        if getattr(user, 'role', '') == 'FACULTY':
            is_assigned_to_user = obj.assignments.filter(
                employee__user=user,
                status='ACTIVE'
            ).exists()
            is_borrowed_by_user = obj.borrowings.filter(
                borrower__user=user,
                status__in=['RELEASED', 'OVERDUE']
            ).exists()
            if not (is_assigned_to_user or is_borrowed_by_user):
                raise PermissionDenied("You only have access to view equipment currently assigned or borrowed under your accountability.")
            return obj

        raise PermissionDenied("You do not have permission to view this asset.")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f"Asset Details: {self.object.asset_code}"

        # Phase 3: Current Assignment & History
        context['current_assignment'] = self.object.assignments.filter(
            status='ACTIVE'
        ).select_related('employee', 'employee__department', 'assigned_by').first()

        context['assignment_history'] = self.object.assignments.filter(
            status='RETURNED'
        ).select_related('employee', 'employee__department', 'assigned_by', 'returned_by').order_by('-returned_date', '-created_at')

        # Phase 4: Current Open Transfer & Movement History
        context['open_transfer'] = self.object.transfers.filter(
            status__in=['PENDING', 'APPROVED']
        ).select_related('from_department', 'from_location', 'to_department', 'to_location', 'requested_by', 'approved_by').first()

        context['movement_history'] = self.object.transfers.filter(
            status='COMPLETED'
        ).select_related(
            'from_department', 'from_location', 'to_department', 'to_location',
            'requested_by', 'approved_by', 'processed_by'
        ).order_by('-completed_at', '-created_at')

        context['can_transfer'] = (
            self.object.status in [Asset.Status.AVAILABLE, Asset.Status.ASSIGNED] and
            context['open_transfer'] is None
        )

        # Phase 6: Physical Verification & QR
        context['latest_verification'] = self.object.verifications.first()
        context['verification_history'] = self.object.verifications.select_related(
            'expected_department', 'expected_location',
            'observed_department', 'observed_location',
            'verified_by'
        ).all()
        context['qr_data_uri'] = qr_services.generate_asset_qr_data_uri(self.object, request=self.request)

        # Phase 7: Equipment Borrowing & Reservation (Faculty)
        context['current_borrowing'] = self.object.borrowings.filter(
            status__in=['RELEASED', 'OVERDUE']
        ).select_related('borrower', 'borrower__department', 'released_by').first()
        context['borrowing_history'] = self.object.borrowings.select_related(
            'borrower', 'borrower__department', 'reviewed_by', 'released_by', 'returned_to'
        ).order_by('-requested_at')[:10]

        # Student Reservations (Phase 2A / 3A)
        user = self.request.user
        can_view_student_pii = user.is_authenticated and (
            getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'ADMIN'
        )
        context['can_view_student_pii'] = can_view_student_pii

        from apps.student_reservations.models import StudentReservation
        from apps.student_reservations.security import mask_contact_info
        from apps.student_reservations.services import auto_expire_uncollected_reservations

        # Lazily transition expired uncollected reservations to NO_SHOW
        auto_expire_uncollected_reservations()

        current_student_loan = self.object.student_reservations.filter(
            status=StudentReservation.Status.RELEASED
        ).first()

        guard_return_pending_inspection = self.object.student_reservations.filter(
            status=StudentReservation.Status.RETURNED_TO_GUARD
        ).first()

        upcoming_student_reservations = list(self.object.student_reservations.filter(
            status=StudentReservation.Status.APPROVED,
            requested_return__gte=timezone.now()
        ).order_by('requested_pickup')[:5])

        student_reservation_history = list(self.object.student_reservations.filter(
            Q(status__in=[
                StudentReservation.Status.RETURNED,
                StudentReservation.Status.REJECTED,
                StudentReservation.Status.CANCELLED,
                StudentReservation.Status.NO_SHOW,
            ]) |
            Q(status=StudentReservation.Status.APPROVED, requested_return__lt=timezone.now())
        ).order_by('-created_at')[:10])

        for res in [current_student_loan, guard_return_pending_inspection] + upcoming_student_reservations + student_reservation_history:
            if res:
                m_email, m_phone = mask_contact_info(res.email, res.contact_number)
                res.masked_email = m_email
                res.masked_phone = m_phone
                if not can_view_student_pii:
                    res.email = m_email
                    res.contact_number = m_phone

        context['current_student_loan'] = current_student_loan
        context['guard_return_pending_inspection'] = guard_return_pending_inspection
        context['upcoming_student_reservations'] = upcoming_student_reservations
        context['student_reservation_history'] = student_reservation_history

        context['can_borrow'] = (
            self.object.status == Asset.Status.AVAILABLE and
            context['current_assignment'] is None and
            context['open_transfer'] is None and
            context['current_borrowing'] is None and
            current_student_loan is None and
            guard_return_pending_inspection is None
        )

        # Phase 8: Maintenance & Defect History
        context['current_maintenance'] = self.object.maintenance_records.filter(
            status__in=['REPORTED', 'ASSESSED', 'IN_REPAIR']
        ).select_related('reported_by', 'assessed_by').first()
        context['maintenance_history'] = self.object.maintenance_records.select_related(
            'reported_by', 'assessed_by', 'returned_to_service_by'
        ).order_by('-reported_at')

        # Phase 9: Disposal & Retirement
        context['disposal_record'] = self.object.disposal_records.filter(
            status='COMPLETED'
        ).select_related('processed_by', 'reviewed_by').first() or self.object.disposal_records.filter(
            status__in=['PENDING', 'APPROVED']
        ).select_related('requested_by', 'reviewed_by').first()
        context['disposal_history'] = self.object.disposal_records.select_related(
            'requested_by', 'reviewed_by', 'processed_by'
        ).order_by('-requested_at')
        context['can_dispose'] = (
            getattr(self.request.user, 'is_admin', False) and
            self.object.status != Asset.Status.DISPOSED and
            not self.object.disposal_records.filter(status__in=['PENDING', 'APPROVED']).exists()
        )

        return context


class AssetCreateView(AdminRequiredMixin, CreateView):
    """
    Registers a new durable college asset.
    Generates unique asset code on save and logs audit event.
    """
    model = Asset
    form_class = AssetForm
    template_name = 'inventory/asset_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)

        # Record audit event
        log_action(
            user=self.request.user,
            action='ASSET_CREATED',
            instance=self.object,
            changes={
                'asset_code': self.object.asset_code,
                'item_name': self.object.item_name,
                'category': str(self.object.category),
                'department': str(self.object.department),
                'status': self.object.status,
                'condition': self.object.condition,
            },
            request=self.request
        )

        messages.success(self.request, f"Asset '{self.object.asset_code}' ({self.object.item_name}) successfully registered.")
        return response

    def get_success_url(self):
        return reverse('inventory:asset_detail', kwargs={'asset_code': self.object.asset_code})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Register New Asset'
        context['is_create'] = True
        return context


class AssetUpdateView(AdminRequiredMixin, UpdateView):
    """
    Edits existing asset specifications and metadata.
    Excludes workflow-managed fields (status, condition, department, current_location).
    Preserves asset_code and records field-level changes in audit log.
    """
    model = Asset
    form_class = AssetUpdateForm
    template_name = 'inventory/asset_form.html'
    slug_field = 'asset_code'
    slug_url_kwarg = 'asset_code'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        old_instance = Asset.objects.get(pk=self.object.pk)

        # Enforce server-side safety locks on workflow-managed fields
        form.instance.status = old_instance.status
        form.instance.condition = old_instance.condition
        form.instance.department = old_instance.department
        form.instance.current_location = old_instance.current_location

        changes = {}
        for field in form.changed_data:
            old_val = getattr(old_instance, field, None)
            new_val = form.cleaned_data.get(field)
            changes[field] = [str(old_val), str(new_val)]

        response = super().form_valid(form)

        # Record audit event
        log_action(
            user=self.request.user,
            action='ASSET_UPDATED',
            instance=self.object,
            changes=changes,
            request=self.request
        )

        messages.success(self.request, f"Asset '{self.object.asset_code}' successfully updated.")
        return response

    def get_success_url(self):
        return reverse('inventory:asset_detail', kwargs={'asset_code': self.object.asset_code})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f"Edit Asset: {self.object.asset_code}"
        context['is_create'] = False
        return context


class AssetDeleteView(AdminRequiredMixin, DeleteView):
    """
    Permanent deletion of asset records with explicit confirmation page.
    Restricted strictly to administrators.
    Prevented if the asset has historical or active assignment records,
    transfers, borrowings, maintenance, disposals, or student reservations.
    """
    model = Asset
    template_name = 'inventory/asset_confirm_delete.html'
    slug_field = 'asset_code'
    slug_url_kwarg = 'asset_code'
    success_url = reverse_lazy('inventory:asset_list')

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.assignments.exists():
            messages.error(
                request,
                f"Asset '{self.object.asset_code}' has accountability history and cannot be permanently deleted."
            )
            return redirect('inventory:asset_detail', asset_code=self.object.asset_code)
        if self.object.transfers.exists():
            messages.error(
                request,
                f"Asset '{self.object.asset_code}' has movement/transfer history and cannot be permanently deleted."
            )
            return redirect('inventory:asset_detail', asset_code=self.object.asset_code)
        if self.object.borrowings.exists():
            messages.error(
                request,
                f"Asset '{self.object.asset_code}' has equipment borrowing history and cannot be permanently deleted."
            )
            return redirect('inventory:asset_detail', asset_code=self.object.asset_code)
        if self.object.maintenance_records.exists():
            messages.error(
                request,
                f"Asset '{self.object.asset_code}' has maintenance/repair history and cannot be permanently deleted."
            )
            return redirect('inventory:asset_detail', asset_code=self.object.asset_code)
        if self.object.disposal_records.exists():
            messages.error(
                request,
                f"Asset '{self.object.asset_code}' has disposal/retirement records and cannot be permanently deleted."
            )
            return redirect('inventory:asset_detail', asset_code=self.object.asset_code)
        if self.object.student_reservations.exists():
            messages.error(
                request,
                f"Asset '{self.object.asset_code}' has student reservation history and cannot be permanently deleted."
            )
            return redirect('inventory:asset_detail', asset_code=self.object.asset_code)
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        if self.object.assignments.exists():
            messages.error(
                self.request,
                f"Asset '{self.object.asset_code}' has accountability history and cannot be permanently deleted."
            )
            return redirect('inventory:asset_detail', asset_code=self.object.asset_code)
        if self.object.transfers.exists():
            messages.error(
                self.request,
                f"Asset '{self.object.asset_code}' has movement/transfer history and cannot be permanently deleted."
            )
            return redirect('inventory:asset_detail', asset_code=self.object.asset_code)
        if self.object.borrowings.exists():
            messages.error(
                self.request,
                f"Asset '{self.object.asset_code}' has equipment borrowing history and cannot be permanently deleted."
            )
            return redirect('inventory:asset_detail', asset_code=self.object.asset_code)
        if self.object.maintenance_records.exists():
            messages.error(
                self.request,
                f"Asset '{self.object.asset_code}' has maintenance/repair history and cannot be permanently deleted."
            )
            return redirect('inventory:asset_detail', asset_code=self.object.asset_code)
        if self.object.disposal_records.exists():
            messages.error(
                self.request,
                f"Asset '{self.object.asset_code}' has disposal/retirement records and cannot be permanently deleted."
            )
            return redirect('inventory:asset_detail', asset_code=self.object.asset_code)
        if self.object.student_reservations.exists():
            messages.error(
                self.request,
                f"Asset '{self.object.asset_code}' has student reservation history and cannot be permanently deleted."
            )
            return redirect('inventory:asset_detail', asset_code=self.object.asset_code)

        asset_code = self.object.asset_code
        item_name = self.object.item_name

        try:
            # Log audit record before deleting
            log_action(
                user=self.request.user,
                action='ASSET_DELETED',
                instance=self.object,
                changes={'asset_code': asset_code, 'item_name': item_name},
                request=self.request
            )

            messages.success(self.request, f"Asset '{asset_code}' ({item_name}) was permanently deleted.")
            return super().form_valid(form)
        except ProtectedError:
            messages.error(
                self.request,
                f"Asset '{asset_code}' cannot be deleted because it is referenced by existing institutional records."
            )
            return redirect('inventory:asset_detail', asset_code=asset_code)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f"Confirm Deletion: {self.object.asset_code}"
        return context


# ==============================================================================
# CATEGORY VIEWS
# ==============================================================================

class CategoryListView(InventoryAccessMixin, ListView):
    model = AssetCategory
    template_name = 'inventory/category_list.html'
    context_object_name = 'categories'
    paginate_by = 10

    def get_queryset(self):
        queryset = super().get_queryset()
        query = self.request.GET.get('q')
        if query:
            queryset = queryset.filter(
                Q(name__icontains=query) | Q(code__icontains=query)
            )
        return queryset


class CategoryCreateView(AdminRequiredMixin, CreateView):
    model = AssetCategory
    form_class = AssetCategoryForm
    template_name = 'inventory/category_form.html'
    success_url = reverse_lazy('inventory:category_list')

    def form_valid(self, form):
        messages.success(self.request, f"Category '{form.cleaned_data['name']}' created successfully.")
        return super().form_valid(form)


class CategoryUpdateView(AdminRequiredMixin, UpdateView):
    model = AssetCategory
    form_class = AssetCategoryForm
    template_name = 'inventory/category_form.html'
    success_url = reverse_lazy('inventory:category_list')

    def form_valid(self, form):
        messages.success(self.request, f"Category '{form.cleaned_data['name']}' updated successfully.")
        return super().form_valid(form)


# ==============================================================================
# BRAND VIEWS
# ==============================================================================

class BrandListView(InventoryAccessMixin, ListView):
    model = Brand
    template_name = 'inventory/brand_list.html'
    context_object_name = 'brands'
    paginate_by = 10

    def get_queryset(self):
        queryset = super().get_queryset()
        query = self.request.GET.get('q')
        if query:
            queryset = queryset.filter(Q(name__icontains=query))
        return queryset


class BrandCreateView(AdminRequiredMixin, CreateView):
    model = Brand
    form_class = BrandForm
    template_name = 'inventory/brand_form.html'
    success_url = reverse_lazy('inventory:brand_list')

    def form_valid(self, form):
        messages.success(self.request, f"Brand '{form.cleaned_data['name']}' created successfully.")
        return super().form_valid(form)


class BrandUpdateView(AdminRequiredMixin, UpdateView):
    model = Brand
    form_class = BrandForm
    template_name = 'inventory/brand_form.html'
    success_url = reverse_lazy('inventory:brand_list')

    def form_valid(self, form):
        messages.success(self.request, f"Brand '{form.cleaned_data['name']}' updated successfully.")
        return super().form_valid(form)


# ==============================================================================
# PHASE 6: QR ASSET TRACKING & PHYSICAL INVENTORY VERIFICATION VIEWS
# ==============================================================================

def check_asset_scan_permission(user, asset):
    """
    Validates whether the user is authorized to view this asset via QR / Scan.
    - Admin & Dean: full access to view any asset.
    - Department Chair: scoped to their department's assets.
    - Faculty: access restricted exclusively to assets actively assigned to them.
    """
    if getattr(user, 'is_admin', False) or getattr(user, 'role', '') == 'DEAN':
        return True

    if getattr(user, 'role', '') == 'DEPT_CHAIR':
        chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
        if chair_dept and asset.department_id == chair_dept.pk:
            return True
        raise PermissionDenied("You do not have permission to view equipment outside your department.")

    if getattr(user, 'role', '') == 'FACULTY':
        is_assigned = asset.assignments.filter(employee__user=user, status='ACTIVE').exists()
        is_borrowed = asset.borrowings.filter(borrower__user=user, status__in=['RELEASED', 'OVERDUE']).exists()
        if is_assigned or is_borrowed:
            return True
        raise PermissionDenied("You only have access to view equipment currently assigned or borrowed under your accountability.")

    raise PermissionDenied("You do not have permission to view this asset.")


class QRAssetLookupView(LoginRequiredMixin, View):
    """
    Dedicated safe gateway route when a QR code sticker is scanned.
    URL: /q/assets/<asset_code>/
    Presents a mobile-first summary with authorized action shortcuts.
    """
    def get(self, request, asset_code):
        asset = get_object_or_404(
            Asset.objects.select_related('category', 'brand', 'department', 'current_location', 'created_by'),
            asset_code=asset_code
        )
        check_asset_scan_permission(request.user, asset)

        current_assignment = asset.assignments.filter(
            status='ACTIVE'
        ).select_related('employee', 'employee__department', 'assigned_by').first()

        open_transfer = asset.transfers.filter(
            status__in=['PENDING', 'APPROVED']
        ).first()

        can_transfer = (
            asset.status in [Asset.Status.AVAILABLE, Asset.Status.ASSIGNED] and
            open_transfer is None
        )

        current_borrowing = asset.borrowings.filter(
            status__in=['RELEASED', 'OVERDUE']
        ).select_related('borrower', 'borrower__department', 'released_by').first()

        can_borrow = (
            asset.status == Asset.Status.AVAILABLE and
            current_assignment is None and
            open_transfer is None and
            current_borrowing is None
        )

        disposal_record = asset.disposal_records.filter(
            status='COMPLETED'
        ).select_related('processed_by').first()

        context = {
            'asset': asset,
            'current_assignment': current_assignment,
            'open_transfer': open_transfer,
            'can_transfer': can_transfer and asset.status != Asset.Status.DISPOSED,
            'current_borrowing': current_borrowing,
            'can_borrow': can_borrow and asset.status != Asset.Status.DISPOSED,
            'disposal_record': disposal_record,
            'latest_verification': asset.verifications.first(),
            'qr_data_uri': qr_services.generate_asset_qr_data_uri(asset, request=request),
            'page_title': f"Asset Lookup: {asset.asset_code}",
        }
        return render(request, 'inventory/qr_asset_lookup.html', context)


class QRAssetImageView(LoginRequiredMixin, View):
    """Returns raw deterministic PNG QR code image for the given asset."""
    def get(self, request, asset_code):
        asset = get_object_or_404(Asset, asset_code=asset_code)
        check_asset_scan_permission(request.user, asset)
        img_bytes = qr_services.generate_asset_qr_image(asset, request=request)
        return HttpResponse(img_bytes, content_type='image/png')


class ScanAssetView(LoginRequiredMixin, FormView):
    """
    Mobile-first camera scanner page with fallback manual asset code input.
    URL: /inventory/scan/
    """
    template_name = 'inventory/scan_asset.html'
    form_class = AssetCodeLookupForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Scan Asset QR Code'
        return context

    def form_valid(self, form):
        asset_code = form.cleaned_data['asset_code']
        asset = Asset.objects.filter(asset_code=asset_code).first()
        if not asset:
            form.add_error('asset_code', f"Asset with code '{asset_code}' was not found in the system.")
            return self.form_invalid(form)
        return redirect('qr_asset_lookup', asset_code=asset.asset_code)


class AssetQRLabelView(LoginRequiredMixin, View):
    """
    Single browser-printable QR sticker label for physical application on durable assets.
    URL: /inventory/assets/<asset_code>/qr-label/
    """
    def get(self, request, asset_code):
        asset = get_object_or_404(
            Asset.objects.select_related('category', 'brand', 'department', 'current_location'),
            asset_code=asset_code
        )
        user = request.user
        # Faculty cannot print institutional QR labels
        if getattr(user, 'role', '') == 'FACULTY':
            raise PermissionDenied("Faculty accounts cannot access asset label printing.")
        check_asset_scan_permission(user, asset)

        qr_data_uri = qr_services.generate_asset_qr_data_uri(asset, request=request)
        context = {
            'asset': asset,
            'qr_data_uri': qr_data_uri,
            'page_title': f"QR Label - {asset.asset_code}",
        }
        return render(request, 'inventory/asset_qr_label.html', context)


class BulkQRLabelPrintView(AdminRequiredMixin, ListView):
    """
    Admin bulk QR label printing center.
    Filters durable assets and outputs a printable 3-column A4 sticker sheet.
    URL: /inventory/qr-labels/
    """
    model = Asset
    template_name = 'inventory/bulk_qr_labels.html'
    context_object_name = 'assets'
    paginate_by = 50

    def get_queryset(self):
        qs = Asset.objects.select_related('category', 'brand', 'department', 'current_location').all()

        dept_id = self.request.GET.get('department')
        loc_id = self.request.GET.get('location')
        cat_id = self.request.GET.get('category')
        status = self.request.GET.get('status')
        q = self.request.GET.get('q', '').strip()

        if q:
            qs = qs.filter(
                Q(asset_code__icontains=q) |
                Q(property_number__icontains=q) |
                Q(item_name__icontains=q) |
                Q(model__icontains=q)
            )
        if dept_id:
            qs = qs.filter(department_id=dept_id)
        if loc_id:
            qs = qs.filter(current_location_id=loc_id)
        if cat_id:
            qs = qs.filter(category_id=cat_id)
        if status:
            qs = qs.filter(status=status)

        # Selected codes from checkbox submission
        selected_codes = self.request.GET.getlist('selected')
        if selected_codes:
            qs = qs.filter(asset_code__in=selected_codes)

        return qs.order_by('asset_code')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Print Asset QR Labels in Bulk'
        context['departments'] = Department.objects.filter(is_active=True)
        context['locations'] = Location.objects.filter(is_active=True)
        context['categories'] = AssetCategory.objects.filter(is_active=True)
        context['statuses'] = Asset.Status.choices

        # Pre-compute data URIs for instantaneous zero-latency printing
        assets_with_qr = []
        for asset in context['assets']:
            assets_with_qr.append({
                'asset': asset,
                'qr_data_uri': qr_services.generate_asset_qr_data_uri(asset, request=self.request),
            })
        context['assets_with_qr'] = assets_with_qr

        # Check if print-only sheet mode
        if self.request.GET.get('print') == 'true':
            self.template_name = 'inventory/bulk_qr_labels_print.html'

        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()
        return context


class AssetVerifyView(AdminRequiredMixin, FormView):
    """
    Physical verification entry view.
    Snapshots database expected state vs physical observed state and determines result.
    URL: /inventory/assets/<asset_code>/verify/
    """
    template_name = 'inventory/asset_verify_form.html'
    form_class = AssetVerificationForm

    def dispatch(self, request, *args, **kwargs):
        self.asset = get_object_or_404(
            Asset.objects.select_related('department', 'current_location', 'category'),
            asset_code=kwargs['asset_code']
        )
        if self.asset.status == Asset.Status.DISPOSED:
            messages.error(request, f"Asset '{self.asset.asset_code}' is disposed and cannot undergo physical inventory verification.")
            return redirect('inventory:asset_detail', asset_code=self.asset.asset_code)
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial_asset'] = self.asset
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['asset'] = self.asset
        context['page_title'] = f"Verify Physical Asset: {self.asset.asset_code}"
        context['latest_verification'] = self.asset.verifications.first()
        context['open_transfer'] = self.asset.transfers.filter(status__in=['PENDING', 'APPROVED']).first()
        return context

    def form_valid(self, form):
        observed_dept = form.cleaned_data['observed_department']
        observed_loc = form.cleaned_data.get('observed_location')
        observed_cond = form.cleaned_data['observed_condition']
        remarks = form.cleaned_data.get('remarks', '')

        verification = qr_services.verify_asset(
            asset=self.asset,
            verified_by=self.request.user,
            observed_department=observed_dept,
            observed_location=observed_loc,
            observed_condition=observed_cond,
            remarks=remarks,
            request=self.request
        )

        res = verification.result
        if res == AssetVerification.VerificationResult.VERIFIED:
            messages.success(
                self.request,
                f"Physical verification recorded for {self.asset.asset_code}: VERIFIED (Exact Match)."
            )
        elif res == AssetVerification.VerificationResult.LOCATION_MISMATCH:
            exp_loc = self.asset.current_location.name if self.asset.current_location else "None"
            obs_loc = observed_loc.name if observed_loc else "None"
            messages.warning(
                self.request,
                f"Physical verification recorded for {self.asset.asset_code}: LOCATION MISMATCH. "
                f"Expected: {self.asset.department.name} ({exp_loc}), Observed: {observed_dept.name} ({obs_loc}). "
                "Canonical asset location remains unchanged. You may initiate a formal transfer."
            )
        elif res == AssetVerification.VerificationResult.CONDITION_MISMATCH:
            messages.warning(
                self.request,
                f"Physical verification recorded for {self.asset.asset_code}: CONDITION MISMATCH. "
                f"Expected: {self.asset.get_condition_display()}, Observed: {verification.get_observed_condition_display()}."
            )
        else:
            messages.warning(
                self.request,
                f"Physical verification recorded for {self.asset.asset_code}: LOCATION & CONDITION MISMATCH."
            )

        # Redirect back to where user came from
        if self.request.GET.get('from') == 'qr':
            return redirect('qr_asset_lookup', asset_code=self.asset.asset_code)
        return redirect('inventory:asset_detail', asset_code=self.asset.asset_code)


class PhysicalVerificationListView(LoginRequiredMixin, ListView):
    """
    Physical Inventory Verification management and history dashboard.
    Surfaces latest verification status across all physical assets.
    URL: /inventory/physical-verification/
    """
    model = Asset
    template_name = 'inventory/physical_verification_list.html'
    context_object_name = 'assets'
    paginate_by = 25

    def get_queryset(self):
        user = self.request.user
        if getattr(user, 'role', '') == 'FACULTY':
            raise PermissionDenied("Faculty accounts cannot access physical inventory verification records.")

        qs = Asset.objects.select_related(
            'category', 'brand', 'department', 'current_location'
        ).prefetch_related(
            'verifications__verified_by',
            'verifications__observed_location',
            'verifications__observed_department'
        )

        # Department scoping for Chairs
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            if chair_dept:
                qs = qs.filter(department=chair_dept)
            else:
                return Asset.objects.none()

        # Filtering
        dept_id = self.request.GET.get('department')
        loc_id = self.request.GET.get('location')
        status = self.request.GET.get('status')
        v_status = self.request.GET.get('v_status')
        q = self.request.GET.get('q', '').strip()

        if q:
            qs = qs.filter(
                Q(asset_code__icontains=q) |
                Q(property_number__icontains=q) |
                Q(item_name__icontains=q) |
                Q(model__icontains=q)
            )
        if dept_id and not (getattr(user, 'role', '') == 'DEPT_CHAIR'):
            qs = qs.filter(department_id=dept_id)
        if loc_id:
            qs = qs.filter(current_location_id=loc_id)
        if status:
            qs = qs.filter(status=status)

        # Verification status filtering
        if v_status == 'VERIFIED':
            qs = qs.filter(verifications__result=AssetVerification.VerificationResult.VERIFIED).distinct()
        elif v_status == 'MISMATCH':
            qs = qs.filter(verifications__result__in=[
                AssetVerification.VerificationResult.LOCATION_MISMATCH,
                AssetVerification.VerificationResult.CONDITION_MISMATCH,
                AssetVerification.VerificationResult.LOCATION_AND_CONDITION_MISMATCH,
            ]).distinct()
        elif v_status == 'NEVER_VERIFIED':
            qs = qs.filter(verifications__isnull=True)

        return qs.order_by('asset_code')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['page_title'] = 'Physical Inventory Verification'

        # Scoped department filter options
        if getattr(user, 'role', '') == 'DEPT_CHAIR':
            chair_dept = getattr(getattr(user, 'employee_profile', None), 'department', None)
            context['departments'] = Department.objects.filter(pk=chair_dept.pk) if chair_dept else Department.objects.none()
            base_qs = Asset.objects.filter(department=chair_dept) if chair_dept else Asset.objects.none()
        else:
            context['departments'] = Department.objects.filter(is_active=True)
            base_qs = Asset.objects.all()

        context['locations'] = Location.objects.filter(is_active=True)
        context['v_results'] = AssetVerification.VerificationResult.choices

        # Aggregate metrics
        thirty_days_ago = timezone.now() - timedelta(days=30)
        context['total_assets_count'] = base_qs.count()
        context['verified_recent_count'] = AssetVerification.objects.filter(
            asset__in=base_qs,
            verified_at__gte=thirty_days_ago,
            result=AssetVerification.VerificationResult.VERIFIED
        ).values('asset_id').distinct().count()
        context['mismatch_count'] = AssetVerification.objects.filter(
            asset__in=base_qs,
            result__in=[
                AssetVerification.VerificationResult.LOCATION_MISMATCH,
                AssetVerification.VerificationResult.CONDITION_MISMATCH,
                AssetVerification.VerificationResult.LOCATION_AND_CONDITION_MISMATCH,
            ]
        ).values('asset_id').distinct().count()
        context['never_verified_count'] = base_qs.filter(verifications__isnull=True).count()

        query_params = self.request.GET.copy()
        if 'page' in query_params:
            query_params.pop('page')
        context['query_string'] = query_params.urlencode()

        return context


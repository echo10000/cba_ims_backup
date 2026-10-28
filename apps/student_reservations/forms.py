import re
from datetime import timedelta
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.inventory.models import Asset, AssetCategory
from .models import StudentReservation


PURPOSE_CHOICES = [
    ('', '-- Select Purpose of Use --'),
    ('Class presentation', 'Class presentation'),
    ('Thesis defense', 'Thesis defense'),
    ('Research presentation', 'Research presentation'),
    ('Classroom activity', 'Classroom activity'),
    ('Seminar / workshop', 'Seminar / workshop'),
    ('Student organization activity', 'Student organization activity'),
    ('College event', 'College event'),
    ('Other', 'Other (specify below)'),
]

VENUE_CHOICES = [
    ('', '-- Select Room or Venue (Optional) --'),
    ('CBA Room 1', 'CBA Room 1'),
    ('CBA Room 2', 'CBA Room 2'),
    ('CBA Room 3', 'CBA Room 3'),
    ('CBA Room 4', 'CBA Room 4'),
    ('CBA Room 5', 'CBA Room 5'),
    ('CBA Room 6', 'CBA Room 6'),
    ('CBA Room 7', 'CBA Room 7'),
    ('CBA Room 8', 'CBA Room 8'),
    ('CBA Room 9', 'CBA Room 9'),
    ('CBA Room 10', 'CBA Room 10'),
    ('CBA Cafeteria', 'CBA Cafeteria'),
    ('Other', 'Other (specify venue below)'),
]


class PublicStudentReservationForm(forms.ModelForm):
    """
    Streamlined public reservation form for students.
    Students do not require accounts or passwords.
    Requires only: ID, Name, Email OR Phone, Category, Pickup, Return, Purpose.
    Optional fields (course/section, venue, equipment preference) placed in collapsible section.
    """
    purpose_details = forms.CharField(
        max_length=300,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Please specify brief activity purpose...'}),
        help_text="Required when 'Other' is selected."
    )
    room_venue_other = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'Specify room or venue name...'}),
        help_text="Required when 'Other' is selected."
    )

    class Meta:
        model = StudentReservation
        fields = [
            'student_id',
            'student_name',
            'course_year_section',
            'email',
            'contact_number',
            'category',
            'equipment_type_ref',
            'equipment_type',
            'requested_pickup',
            'requested_return',
            'purpose',
            'room_venue',
        ]
        widgets = {
            'requested_pickup': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'requested_return': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'purpose': forms.Select(choices=PURPOSE_CHOICES),
            'room_venue': forms.Select(choices=VENUE_CHOICES),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.inventory.models import EquipmentType
        # Only expose active, reservable categories in the public catalog
        self.fields['category'].queryset = AssetCategory.objects.filter(
            is_active=True,
            is_reservable=True
        )

        # Expose active equipment types
        self.fields['equipment_type_ref'].queryset = EquipmentType.objects.filter(
            is_active=True,
            category__is_active=True,
            category__is_reservable=True
        ).select_related('category')
        self.fields['equipment_type_ref'].required = False
        self.fields['equipment_type_ref'].empty_label = "-- Select Equipment Type --"

        # Filter equipment_type_ref queryset if category is already selected/bound
        category_id = self.data.get('category') or self.initial.get('category')
        if category_id:
            try:
                cat_pk = getattr(category_id, 'pk', category_id)
                self.fields['equipment_type_ref'].queryset = self.fields['equipment_type_ref'].queryset.filter(
                    category_id=cat_pk
                )
            except (ValueError, TypeError):
                pass

        # Make course/year/section, email, and contact_number optional on the individual field level;
        # contact enforcement (email OR phone) is checked in clean().
        self.fields['course_year_section'].required = False
        self.fields['email'].required = False
        self.fields['contact_number'].required = False
        self.fields['room_venue'].required = False
        self.fields['equipment_type'].required = False

        # Handle room_venue dropdown vs custom venue
        initial_venue = self.initial.get('room_venue') or (self.instance.room_venue if self.instance.pk else '')
        if initial_venue:
            standard_venues = [c[0] for c in VENUE_CHOICES if c[0] and c[0] != 'Other']
            if initial_venue in standard_venues:
                self.initial['room_venue'] = initial_venue
            else:
                self.initial['room_venue'] = 'Other'
                self.initial['room_venue_other'] = initial_venue

        # If existing purpose instance value doesn't match predefined choices, preserve it in details
        initial_purpose = self.initial.get('purpose') or (self.instance.purpose if self.instance.pk else None)
        if initial_purpose:
            known_choices = [c[0] for c in PURPOSE_CHOICES if c[0]]
            legacy_map = {
                'Class Presentation / Reporting': 'Class presentation',
                'Thesis / Capstone / Research Defense': 'Thesis defense',
                'Student Organization Activity': 'Student organization activity',
                'Department / College Seminar or Event': 'College event',
            }
            if initial_purpose in legacy_map:
                self.initial['purpose'] = legacy_map[initial_purpose]
            elif initial_purpose not in known_choices:
                # Value was entered freeform or with 'Other:'
                if initial_purpose.startswith('Other: '):
                    self.initial['purpose'] = 'Other'
                    self.initial['purpose_details'] = initial_purpose[7:]
                else:
                    self.initial['purpose'] = 'Other'
                    self.initial['purpose_details'] = initial_purpose

    def clean_student_id(self):
        val = self.cleaned_data.get('student_id', '').strip()
        if not val:
            raise ValidationError("Student ID number is required.")
        # Common university student ID pattern: e.g. 9-digit format (2024XXXXX) or alphanumeric with hyphens
        if not re.match(r'^[A-Za-z0-9\-]{4,30}$', val):
            raise ValidationError("Please enter a valid Student ID format (e.g. 2024XXXXX).")
        return val

    def clean_student_name(self):
        val = self.cleaned_data.get('student_name', '').strip()
        if len(val) < 2:
            raise ValidationError("Please enter your full legal name.")
        if not re.match(r"^[A-Za-z\s\.\,\'\-]+$", val):
            raise ValidationError("Student name contains invalid characters.")
        return val

    def clean_course_year_section(self):
        val = self.cleaned_data.get('course_year_section', '')
        return val.strip() if val else ''

    def clean_email(self):
        val = self.cleaned_data.get('email', '')
        return val.strip().lower() if val else ''

    def clean_contact_number(self):
        val = self.cleaned_data.get('contact_number', '')
        if not val:
            return ''
        cleaned_phone = re.sub(r'[\s\-\(\)]', '', val.strip())
        if not re.match(r'^\+?[0-9]{7,15}$', cleaned_phone):
            raise ValidationError("Please enter a valid mobile or phone number (e.g. 09171234567).")
        return val.strip()

    def clean_purpose(self):
        val = self.cleaned_data.get('purpose', '').strip()
        if not val:
            raise ValidationError("Please select the purpose of equipment use.")
        return val

    def clean(self):
        cleaned_data = super().clean()
        pickup = cleaned_data.get('requested_pickup')
        ret = cleaned_data.get('requested_return')
        category = cleaned_data.get('category')
        email = cleaned_data.get('email', '')
        contact = cleaned_data.get('contact_number', '')
        purpose = cleaned_data.get('purpose', '')
        purpose_details = cleaned_data.get('purpose_details', '').strip()

        # Enforce at least one contact method (email OR phone)
        if not email and not contact:
            err_msg = "Please provide at least one contact method (email or mobile number)."
            self.add_error('email', err_msg)
            self.add_error('contact_number', err_msg)

        # Handle Purpose dropdown + conditional 'Other' details
        if purpose == 'Other':
            if not purpose_details:
                self.add_error('purpose_details', "Please briefly specify your activity purpose.")
            else:
                cleaned_data['purpose'] = f"Other: {purpose_details}"
        elif purpose_details:
            cleaned_data['purpose'] = f"{purpose} - {purpose_details}"

        # Handle Room / Venue dropdown + conditional 'Other' details
        room_venue = cleaned_data.get('room_venue', '').strip()
        room_venue_other = cleaned_data.get('room_venue_other', '').strip()
        if room_venue == 'Other':
            if not room_venue_other:
                self.add_error('room_venue_other', "Please specify your room or venue.")
            else:
                cleaned_data['room_venue'] = room_venue_other
        elif room_venue:
            cleaned_data['room_venue'] = room_venue
        elif room_venue_other:
            cleaned_data['room_venue'] = room_venue_other
        else:
            cleaned_data['room_venue'] = ''

        # Schedule validation
        if pickup and ret:
            if pickup >= ret:
                self.add_error('requested_return', "Requested return time must be strictly after the pickup time.")

            now = timezone.now()
            # Allow up to 10 minutes clock skew in the past for immediate walk-in reservations
            if pickup < now - timedelta(minutes=10):
                self.add_error('requested_pickup', "Requested pickup time cannot be in the past.")

        if category:
            if not getattr(category, 'is_reservable', True) or not getattr(category, 'is_active', True):
                self.add_error('category', f"Category '{category.name}' is not currently available for reservations.")

            from apps.inventory.models import EquipmentType
            active_types = EquipmentType.objects.filter(category=category, is_active=True)
            equipment_type_ref = cleaned_data.get('equipment_type_ref')
            if active_types.exists():
                if not equipment_type_ref:
                    self.add_error('equipment_type_ref', f"Please select a specific equipment type for {category.name}.")
                elif equipment_type_ref.category_id != category.id:
                    self.add_error('equipment_type_ref', f"Selected equipment type does not belong to category '{category.name}'.")

            if equipment_type_ref and not cleaned_data.get('equipment_type'):
                cleaned_data['equipment_type'] = equipment_type_ref.name

        return cleaned_data


class CustodianApprovalForm(forms.Form):
    """
    Form for Custodian to allocate an asset and approve a student reservation.
    """
    asset = forms.ModelChoiceField(
        queryset=Asset.objects.none(),
        required=True,
        help_text="Select an available physical asset to allocate."
    )
    grace_period_minutes = forms.IntegerField(
        initial=15,
        min_value=5,
        max_value=120,
        required=True,
        help_text="Pickup grace period in minutes (default 15)."
    )
    remarks = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2}),
        required=False
    )

    def __init__(self, reservation, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .services import get_available_assets_for_category
        available = get_available_assets_for_category(
            category=reservation.category,
            requested_pickup=reservation.requested_pickup,
            requested_return=reservation.requested_return,
            equipment_type=reservation.equipment_type,
            equipment_type_ref=reservation.equipment_type_ref,
            exclude_student_reservation_id=reservation.pk
        )
        pks = [a.pk for a in available]
        self.fields['asset'].queryset = Asset.objects.filter(pk__in=pks)


class CustodianRejectionForm(forms.Form):
    rejection_reason = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 3}),
        required=True,
        help_text="Explanation for rejecting the reservation."
    )


class CustodianReleaseForm(forms.Form):
    condition_at_release = forms.ChoiceField(
        choices=Asset.Condition.choices,
        required=True,
        initial=Asset.Condition.GOOD,
        help_text="Physical condition snapshot upon equipment release."
    )
    id_deposited = forms.BooleanField(
        required=True,
        initial=True,
        label="Student School ID Verified and Deposited at CBA Office"
    )
    remarks = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2}),
        required=False
    )

    def clean_condition_at_release(self):
        cond = self.cleaned_data.get('condition_at_release')
        if cond == Asset.Condition.UNSERVICEABLE:
            raise ValidationError("Cannot release equipment in UNSERVICEABLE condition.")
        return cond


class CustodianOfficeReturnForm(forms.Form):
    condition_at_return = forms.ChoiceField(
        choices=Asset.Condition.choices,
        required=True,
        help_text="Inspected physical condition upon return."
    )
    return_remarks = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2}),
        required=False
    )
    id_collected_now = forms.BooleanField(
        required=False,
        initial=True,
        label="Deposited School ID Handed Back to Student"
    )


class CustodianGuardReturnForm(forms.Form):
    guard_returned_at = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        required=True,
        help_text="Actual documented handover datetime to security guard."
    )
    guard_handover_details = forms.CharField(
        max_length=255,
        required=True,
        help_text="Guard name, guard post, or logbook entry number."
    )
    remarks = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2}),
        required=False
    )

    def clean_guard_returned_at(self):
        val = self.cleaned_data.get('guard_returned_at')
        if val and val > timezone.now():
            raise ValidationError("Handover time to security guard cannot be in the future.")
        return val


class CustodianGuardInspectionForm(forms.Form):
    condition_at_return = forms.ChoiceField(
        choices=Asset.Condition.choices,
        required=True,
        help_text="Inspected physical condition of guard-returned equipment."
    )
    inspection_remarks = forms.CharField(
        widget=forms.Textarea(attrs={'rows': 2}),
        required=False,
        help_text="Inspection notes (e.g. cables, completeness, lamp hours)."
    )
    id_collected_now = forms.BooleanField(
        required=False,
        initial=False,
        label="Deposited School ID Handed Back to Student (if student is present)"
    )


class CustodianIDCollectionForm(forms.Form):
    confirm_handed_back = forms.BooleanField(
        required=True,
        label="I confirm that the physical School ID has been handed back to the student."
    )
    remarks = forms.CharField(
        max_length=255,
        required=False,
        help_text="Remarks regarding school ID return (e.g. verified student signature)."
    )

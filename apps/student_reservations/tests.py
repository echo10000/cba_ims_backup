from datetime import timedelta, date
from decimal import Decimal
from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.cache import cache

from apps.accounts.models import User
from apps.organizations.models import Department, Location, Employee
from apps.inventory.models import AssetCategory, Brand, Asset, EquipmentType
from apps.borrowing.models import AssetBorrowing
from apps.borrowing import services as borrowing_services
from apps.assignments.models import AssetAssignment
from apps.assignments import services as assignment_services
from apps.student_reservations.models import StudentReservation
from apps.student_reservations import services as student_services
from apps.student_reservations.security import check_submission_rate_limit, mask_contact_info


class StudentReservationBaseTestCase(TestCase):
    """Sets up standard organizational structure, users, assets, and categories."""

    def setUp(self):
        cache.clear()

        # Department & Location
        self.dept_cba = Department.objects.create(code='CBA', name='College of Business Administration')
        self.loc_office = Location.objects.create(
            name='CBA Property Office',
            building='CBA Main',
            room_number='101',
            department=self.dept_cba
        )

        # Users
        self.custodian_user = User.objects.create_superuser(
            'custodian', 'custodian@cba.edu', 'Pass1234!', role=User.Role.ADMIN
        )
        self.faculty_user = User.objects.create_user(
            'faculty_prof', 'faculty@cba.edu', 'Pass1234!', role=User.Role.FACULTY
        )
        self.chair_user = User.objects.create_user(
            'dept_chair', 'chair@cba.edu', 'Pass1234!', role=User.Role.DEPT_CHAIR
        )

        # Employee Profile for Faculty
        self.emp_faculty = Employee.objects.create(
            user=self.faculty_user,
            employee_id='EMP-FAC-99',
            first_name='Juan',
            last_name='Luna',
            department=self.dept_cba,
            location=self.loc_office,
            position='Instructor',
            is_active=True
        )

        # Categories
        self.cat_av = AssetCategory.objects.create(
            code='AV',
            name='Audio-Visual',
            is_active=True,
            is_reservable=True
        )
        self.cat_furniture = AssetCategory.objects.create(
            code='FN',
            name='Office Furniture',
            is_active=True,
            is_reservable=False  # Non-reservable
        )

        self.brand_epson = Brand.objects.create(name='Epson')

        # The office has three individually tracked projectors
        self.proj_1 = Asset.objects.create(
            item_name='Epson EB-X06 Projector 1',
            category=self.cat_av,
            brand=self.brand_epson,
            model='EB-X06',
            serial_number='SN-PROJ-001',
            property_number='CBA-PROP-PROJ-01',
            department=self.dept_cba,
            current_location=self.loc_office,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            is_reservable=True
        )
        self.proj_2 = Asset.objects.create(
            item_name='Epson EB-X06 Projector 2',
            category=self.cat_av,
            brand=self.brand_epson,
            model='EB-X06',
            serial_number='SN-PROJ-002',
            property_number='CBA-PROP-PROJ-02',
            department=self.dept_cba,
            current_location=self.loc_office,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            is_reservable=True
        )
        self.proj_3 = Asset.objects.create(
            item_name='Epson EB-X06 Projector 3',
            category=self.cat_av,
            brand=self.brand_epson,
            model='EB-X06',
            serial_number='SN-PROJ-003',
            property_number='CBA-PROP-PROJ-03',
            department=self.dept_cba,
            current_location=self.loc_office,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            is_reservable=True
        )

        # Default requested intervals
        self.now = timezone.localtime()
        self.t_start = self.now + timedelta(hours=2)
        self.t_end = self.t_start + timedelta(hours=2)


class StudentReservationLifecycleTestCase(StudentReservationBaseTestCase):
    """Tests reservation submission, approval, release, direct return, and cancellation."""

    def test_reservation_creation(self):
        """Students can submit a reservation without an account, generating an unguessable token."""
        res = student_services.submit_reservation(
            student_id='2024-10001',
            student_name='Clara Del Rosario',
            course_year_section='BSBA 3-B',
            email='clara@student.cba.edu',
            contact_number='09171234567',
            category=self.cat_av,
            equipment_type='Projector',
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Marketing presentation in Rm 204',
            room_venue='Room 204'
        )

        self.assertEqual(res.status, StudentReservation.Status.PENDING)
        self.assertIsNone(res.asset)
        self.assertEqual(len(res.lookup_token), 43)
        self.assertTrue(len(res.lookup_token) >= 32)
        self.assertEqual(res.student_id, '2024-10001')
        self.assertEqual(res.category, self.cat_av)
        self.assertFalse(res.id_deposit_verified)
        self.assertIsNone(res.id_deposited_at)
        self.assertIsNone(res.id_collected_at)

    def test_approval_and_allocation(self):
        """Property Custodian can approve a pending reservation by allocating an available asset."""
        res = student_services.submit_reservation(
            student_id='2024-10001',
            student_name='Clara Del Rosario',
            course_year_section='BSBA 3-B',
            email='clara@student.cba.edu',
            contact_number='09171234567',
            category=self.cat_av,
            equipment_type='Projector',
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Presentation'
        )

        approved_res = student_services.approve_reservation(
            reservation=res,
            asset=self.proj_1,
            reviewed_by=self.custodian_user,
            grace_period_minutes=15,
            remarks='Allocated Unit 1'
        )

        self.assertEqual(approved_res.status, StudentReservation.Status.APPROVED)
        self.assertEqual(approved_res.asset, self.proj_1)
        self.assertEqual(approved_res.reviewed_by, self.custodian_user)
        self.assertIsNotNone(approved_res.reviewed_at)
        self.assertEqual(approved_res.grace_period_minutes, 15)

    def test_release_and_school_id_deposit(self):
        """Physical equipment release records original school ID deposit and updates asset status to BORROWED."""
        res = student_services.submit_reservation(
            student_id='2024-10001',
            student_name='Clara Del Rosario',
            course_year_section='BSBA 3-B',
            email='clara@student.cba.edu',
            contact_number='09171234567',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Presentation'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user)

        released_res = student_services.release_equipment(
            reservation=res,
            released_by=self.custodian_user,
            condition_at_release=Asset.Condition.GOOD,
            id_deposited=True
        )

        self.assertEqual(released_res.status, StudentReservation.Status.RELEASED)
        self.assertTrue(released_res.id_deposit_verified)
        self.assertIsNotNone(released_res.id_deposited_at)
        self.assertTrue(released_res.is_id_in_custody)

        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.BORROWED)

    def test_direct_office_return_and_id_collection(self):
        """Direct office return restores asset to AVAILABLE and allows student to collect deposited ID."""
        res = student_services.submit_reservation(
            student_id='2024-10001',
            student_name='Clara Del Rosario',
            course_year_section='BSBA 3-B',
            email='clara@student.cba.edu',
            contact_number='09171234567',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Presentation'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user)
        student_services.release_equipment(res, self.custodian_user, id_deposited=True)

        returned_res = student_services.return_equipment_to_office(
            reservation=res,
            returned_to=self.custodian_user,
            condition_at_return=Asset.Condition.GOOD,
            return_remarks='Returned complete with HDMI cable',
            id_collected_now=True
        )

        self.assertEqual(returned_res.status, StudentReservation.Status.RETURNED)
        self.assertIsNotNone(returned_res.returned_at)
        self.assertIsNotNone(returned_res.id_collected_at)
        self.assertFalse(returned_res.is_id_in_custody)

        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.AVAILABLE)

    def test_direct_office_return_unserviceable_sets_damaged(self):
        """Returning unserviceable/broken equipment sets canonical asset status to DAMAGED."""
        res = student_services.submit_reservation(
            student_id='2024-10001',
            student_name='Clara Del Rosario',
            course_year_section='BSBA 3-B',
            email='clara@student.cba.edu',
            contact_number='09171234567',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Presentation'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user)
        student_services.release_equipment(res, self.custodian_user, id_deposited=True)

        student_services.return_equipment_to_office(
            reservation=res,
            returned_to=self.custodian_user,
            condition_at_return=Asset.Condition.UNSERVICEABLE,
            return_remarks='Lens cracked and power port loose'
        )

        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.DAMAGED)
        self.assertEqual(self.proj_1.condition, Asset.Condition.UNSERVICEABLE)

    def test_rejection_and_cancellation(self):
        """Custodians can reject with reason; students can cancel pending reservations using token."""
        res1 = student_services.submit_reservation(
            student_id='2024-10001',
            student_name='Student 1',
            course_year_section='BSBA 1-A',
            email='s1@student.cba.edu',
            contact_number='09170000001',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Purpose'
        )
        rejected = student_services.reject_reservation(
            res1, self.custodian_user, rejection_reason='Equipment scheduled for maintenance'
        )
        self.assertEqual(rejected.status, StudentReservation.Status.REJECTED)
        self.assertEqual(rejected.rejection_reason, 'Equipment scheduled for maintenance')

        res2 = student_services.submit_reservation(
            student_id='2024-10002',
            student_name='Student 2',
            course_year_section='BSBA 1-B',
            email='s2@student.cba.edu',
            contact_number='09170000002',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Purpose'
        )
        cancelled = student_services.cancel_reservation(
            res2, lookup_token=res2.lookup_token, reason='Activity cancelled by professor'
        )
        self.assertEqual(cancelled.status, StudentReservation.Status.CANCELLED)


class ThreeProjectorAvailabilityTestCase(StudentReservationBaseTestCase):
    """
    Tests the confirmed business rule:
    'The office has three individually tracked projectors.
    Students request an equipment type; the Custodian allocates a specific available asset when approving.'
    """

    def test_three_projectors_saturation_and_availability(self):
        """Checks availability counts and allocation when all 3 projectors are booked."""
        # 1. Initial state: All 3 projectors available
        avail = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end
        )
        self.assertEqual(len(avail), 3)

        # 2. Student 1 reserves and is allocated Proj 1
        r1 = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Presentation'
        )
        student_services.approve_reservation(r1, self.proj_1, self.custodian_user)

        # 2 projectors remaining
        avail = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end
        )
        self.assertEqual(len(avail), 2)
        self.assertNotIn(self.proj_1, avail)

        # 3. Student 2 reserves overlapping slot (starts 30m later) and is allocated Proj 2
        r2 = student_services.submit_reservation(
            'ST-2', 'Student 2', 'BSBA 2', 's2@cba.edu', '09172222222',
            self.cat_av, self.t_start + timedelta(minutes=30), self.t_end, 'Defense'
        )
        student_services.approve_reservation(r2, self.proj_2, self.custodian_user)

        # 1 projector remaining
        avail = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end
        )
        self.assertEqual(len(avail), 1)
        self.assertEqual(avail[0], self.proj_3)

        # 4. Student 3 reserves overlapping slot and is allocated Proj 3
        r3 = student_services.submit_reservation(
            'ST-3', 'Student 3', 'BSBA 3', 's3@cba.edu', '09173333333',
            self.cat_av, self.t_start, self.t_end, 'Webinar'
        )
        student_services.approve_reservation(r3, self.proj_3, self.custodian_user)

        # 0 projectors remaining for this overlapping slot
        avail = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end
        )
        self.assertEqual(len(avail), 0)

        # 5. A 4th overlapping reservation cannot allocate any projector
        r4 = student_services.submit_reservation(
            'ST-4', 'Student 4', 'BSBA 4', 's4@cba.edu', '09174444444',
            self.cat_av, self.t_start, self.t_end, 'Class'
        )
        with self.assertRaises(ValidationError):
            student_services.approve_reservation(r4, self.proj_1, self.custodian_user)

        # 6. Non-overlapping future slot (later that day) still has all 3 projectors available
        future_start = self.t_end + timedelta(hours=1)
        future_end = future_start + timedelta(hours=2)
        future_avail = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=future_start,
            requested_return=future_end
        )
        self.assertEqual(len(future_avail), 3)

        # 7. If Student 1 cancels, Proj 1 immediately becomes available again
        student_services.cancel_reservation(r1, lookup_token=r1.lookup_token)
        avail = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end
        )
        self.assertEqual(len(avail), 1)
        self.assertEqual(avail[0], self.proj_1)


class OverlappingAndConflictTestCase(StudentReservationBaseTestCase):
    """Tests strict prevention of overlapping bookings and double-booking."""

    def test_prevent_double_booking_same_asset(self):
        """An asset approved for interval [t1, t2] cannot be allocated to another reservation overlapping [t1, t2]."""
        r1 = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Event'
        )
        student_services.approve_reservation(r1, self.proj_1, self.custodian_user)

        r2 = student_services.submit_reservation(
            'ST-2', 'Student 2', 'BSBA 2', 's2@cba.edu', '09172222222',
            self.cat_av, self.t_start + timedelta(minutes=15), self.t_end + timedelta(minutes=15), 'Event'
        )
        with self.assertRaises(ValidationError) as ctx:
            student_services.approve_reservation(r2, self.proj_1, self.custodian_user)
        self.assertIn("overlapping approved student reservation", str(ctx.exception))

    def test_pending_reservations_do_not_block_equipment(self):
        """Confirmed rule: Pending requests do not block equipment until Custodian approval."""
        r1 = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Event'
        )
        self.assertEqual(r1.status, StudentReservation.Status.PENDING)

        # All 3 projectors must still be available
        avail = student_services.get_available_assets_for_category(
            self.cat_av, self.t_start, self.t_end
        )
        self.assertEqual(len(avail), 3)


class SharedAvailabilityIntegrationTestCase(StudentReservationBaseTestCase):
    """
    Tests shared availability rules:
    - Existing faculty borrowings block student reservations.
    - Student reservations block faculty borrowings.
    - Active employee assignments block student reservations.
    - Student reservations block employee assignments.
    """

    def test_faculty_borrowing_blocks_student_reservation(self):
        """Faculty borrowing in apps/borrowing blocks student reservation for that interval."""
        # Faculty borrows Proj 1
        borrowing = borrowing_services.request_borrowing(
            asset=self.proj_1,
            borrower=self.emp_faculty,
            purpose='Lecture instruction',
            requested_start=self.t_start,
            requested_return=self.t_end
        )
        borrowing_services.approve_borrowing(borrowing, reviewed_by=self.custodian_user)

        # Check availability for student reservation: Proj 1 must not be available
        avail = student_services.get_available_assets_for_category(
            self.cat_av, self.t_start, self.t_end
        )
        self.assertNotIn(self.proj_1, avail)

        # Attempting to allocate Proj 1 to a student reservation must raise ValidationError
        student_res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Student Meeting'
        )
        with self.assertRaises(ValidationError) as ctx:
            student_services.approve_reservation(student_res, self.proj_1, self.custodian_user)
        self.assertIn("overlapping faculty borrowing", str(ctx.exception))

    def test_student_reservation_blocks_faculty_borrowing(self):
        """Approved student reservation blocks faculty borrowing from taking the same equipment."""
        student_res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Classroom Activity'
        )
        student_services.approve_reservation(student_res, self.proj_1, self.custodian_user)

        # Faculty attempts to request Proj 1 for the same interval
        with self.assertRaises(ValidationError) as ctx:
            borrowing_services.request_borrowing(
                asset=self.proj_1,
                borrower=self.emp_faculty,
                purpose='Faculty instruction',
                requested_start=self.t_start,
                requested_return=self.t_end
            )
        self.assertIn("already reserved for a student", str(ctx.exception))

    def test_active_assignment_blocks_student_reservation(self):
        """Asset with active long-term AssetAssignment cannot be reserved by students."""
        assignment_services.assign_asset(
            asset=self.proj_2,
            employee=self.emp_faculty,
            assigned_by=self.custodian_user,
            purpose='Permanent office accountability'
        )

        avail = student_services.get_available_assets_for_category(
            self.cat_av, self.t_start, self.t_end
        )
        self.assertNotIn(self.proj_2, avail)

        student_res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Presentation'
        )
        with self.assertRaises(ValidationError) as ctx:
            student_services.approve_reservation(student_res, self.proj_2, self.custodian_user)
        self.assertIn("ongoing employee accountability", str(ctx.exception))

    def test_student_reservation_blocks_assignment(self):
        """Asset with approved student reservation cannot be assigned under ongoing employee accountability."""
        student_res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Presentation'
        )
        student_services.approve_reservation(student_res, self.proj_1, self.custodian_user)

        with self.assertRaises(ValidationError) as ctx:
            assignment_services.assign_asset(
                asset=self.proj_1,
                employee=self.emp_faculty,
                assigned_by=self.custodian_user,
                purpose='New assignment'
            )
        self.assertIn("approved or active student reservation", str(ctx.exception))


class NoShowAndGracePeriodTestCase(StudentReservationBaseTestCase):
    """
    Tests pickup grace period (15 minutes default, extendable) and no-show handling.
    Confirmed rule: 'Treat expired uncollected reservations correctly, without requiring a background task.'
    """

    def test_grace_period_calculation_and_extension(self):
        """Default grace period is 15 minutes; Custodian can extend it."""
        pickup = self.now + timedelta(minutes=10)
        res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, pickup, pickup + timedelta(hours=2), 'Presentation'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user, grace_period_minutes=15)

        self.assertEqual(res.grace_period_minutes, 15)
        self.assertEqual(res.pickup_deadline, pickup + timedelta(minutes=15))

        # Custodian extends grace period by 20 minutes
        student_services.extend_grace_period(
            res, additional_minutes=20, extended_by=self.custodian_user, reason='Student delayed in traffic'
        )
        res.refresh_from_db()
        self.assertEqual(res.grace_period_minutes, 35)
        self.assertEqual(res.pickup_deadline, pickup + timedelta(minutes=35))

    def test_expired_uncollected_reservation_does_not_block_equipment(self):
        """
        When pickup grace deadline has passed, the approved reservation is expired
        and does NOT block other bookings, even without an external cron/celery worker.
        """
        past_pickup = self.now - timedelta(minutes=30)
        res = StudentReservation.objects.create(
            student_id='ST-1',
            student_name='Student 1',
            course_year_section='BSBA 1',
            email='s1@cba.edu',
            contact_number='09171111111',
            category=self.cat_av,
            asset=self.proj_1,
            requested_pickup=past_pickup,
            requested_return=past_pickup + timedelta(hours=2),
            purpose='Presentation',
            status=StudentReservation.Status.APPROVED,
            reviewed_by=self.custodian_user,
            reviewed_at=past_pickup - timedelta(hours=1),
            grace_period_minutes=15
        )

        # 30 minutes have passed since pickup; with 15m grace period, deadline was 15m ago
        self.assertTrue(res.is_pickup_expired)

        # Checking availability for Proj 1 for a new reservation right now
        avail = student_services.get_available_assets_for_category(
            self.cat_av, self.now, self.now + timedelta(hours=2)
        )
        # Proj 1 is treated as available because previous reservation expired uncollected!
        self.assertIn(self.proj_1, avail)

        # Auto-expiration lazily marks it as NO_SHOW in DB
        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.NO_SHOW)

    def test_releasing_expired_reservation_without_extension_fails(self):
        """Attempting to release an approved reservation after grace period expires raises ValidationError."""
        past_pickup = self.now - timedelta(minutes=20)
        res = StudentReservation.objects.create(
            student_id='ST-1',
            student_name='Student 1',
            course_year_section='BSBA 1',
            email='s1@cba.edu',
            contact_number='09171111111',
            category=self.cat_av,
            asset=self.proj_1,
            requested_pickup=past_pickup,
            requested_return=past_pickup + timedelta(hours=2),
            purpose='Presentation',
            status=StudentReservation.Status.APPROVED,
            reviewed_by=self.custodian_user,
            reviewed_at=past_pickup - timedelta(hours=1),
            grace_period_minutes=15
        )

        with self.assertRaises(ValidationError) as ctx:
            student_services.release_equipment(res, self.custodian_user, id_deposited=True)
        err = str(ctx.exception)
        self.assertTrue("Pickup grace period expired" in err or "No Show" in err)


class GuardReturnWorkflowTestCase(StudentReservationBaseTestCase):
    """
    Tests security guard return and CBA office inspection workflow:
    - Return to guard after hours.
    - CBA records handover next day using actual documented handover time.
    - Asset remains unavailable (BORROWED) until CBA inspects it.
    - Student collects deposited ID at CBA office.
    """

    def test_guard_return_and_cba_inspection_workflow(self):
        """Complete workflow for after-hours guard handover and inspection."""
        res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Evening Study'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user)
        student_services.release_equipment(res, self.custodian_user, id_deposited=True)

        # Simulate elapsed time so handover occurred earlier today
        released_time = self.now - timedelta(hours=3)
        guard_handover_time = self.now - timedelta(hours=1)
        StudentReservation.objects.filter(pk=res.pk).update(released_at=released_time)
        res.refresh_from_db()

        recorded_guard_res = student_services.record_guard_return(
            reservation=res,
            recorded_by=self.custodian_user,
            guard_returned_at=guard_handover_time,
            guard_handover_details='Security Guard R. Cruz, CBA Lobby Post Logbook Entry #88',
            remarks='Handed over to guard at 7:15 PM'
        )

        self.assertEqual(recorded_guard_res.status, StudentReservation.Status.RETURNED_TO_GUARD)
        self.assertEqual(recorded_guard_res.guard_returned_at, guard_handover_time)
        self.assertEqual(recorded_guard_res.guard_recorded_by, self.custodian_user)

        # Asset remains BORROWED / unavailable until inspected!
        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.BORROWED)

        # Student ID is still deposited in CBA office (guard does NOT have the ID)
        self.assertTrue(recorded_guard_res.is_id_in_custody)
        self.assertIsNone(recorded_guard_res.id_collected_at)

        # Proj 1 is completely unavailable for other reservations
        is_avail, reason = student_services.check_asset_availability(
            self.proj_1, self.t_end + timedelta(hours=2), self.t_end + timedelta(hours=4)
        )
        self.assertFalse(is_avail)
        self.assertIn("awaiting CBA inspection", reason)

        # Next working day: CBA Custodian completes inspection
        inspected_res = student_services.complete_inspection(
            reservation=recorded_guard_res,
            inspected_by=self.custodian_user,
            condition_at_return=Asset.Condition.GOOD,
            inspection_remarks='Tested unit, bulb working, remote and VGA/HDMI cables present',
            id_collected_now=False
        )

        self.assertEqual(inspected_res.status, StudentReservation.Status.RETURNED)
        self.assertIsNotNone(inspected_res.cba_inspected_at)

        # Proj 1 is now AVAILABLE again
        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.AVAILABLE)

        # Student subsequently visits CBA office to collect their deposited school ID
        collected_id_res = student_services.record_id_collection(
            reservation=inspected_res,
            returned_by=self.custodian_user,
            remarks='Original school ID released to student Clara upon signing logbook'
        )
        self.assertIsNotNone(collected_id_res.id_collected_at)
        self.assertFalse(collected_id_res.is_id_in_custody)


class OverdueCalculationTestCase(StudentReservationBaseTestCase):
    """Tests overdue calculations based on expected return deadline and actual handover time."""

    def test_released_equipment_overdue(self):
        """Released equipment past return deadline is dynamically calculated as overdue."""
        past_start = self.now - timedelta(hours=3)
        past_return = self.now - timedelta(hours=1)

        res = StudentReservation.objects.create(
            student_id='ST-1',
            student_name='Student 1',
            course_year_section='BSBA 1',
            email='s1@cba.edu',
            contact_number='09171111111',
            category=self.cat_av,
            asset=self.proj_1,
            requested_pickup=past_start,
            requested_return=past_return,
            purpose='Event',
            status=StudentReservation.Status.RELEASED,
            released_by=self.custodian_user,
            released_at=past_start,
            id_deposit_verified=True
        )

        self.assertTrue(res.is_overdue)
        self.assertGreater(res.overdue_duration.total_seconds(), 0)

    def test_guard_return_overdue_calculation(self):
        """Guard return handed over past deadline is calculated as overdue using documented handover time."""
        past_start = self.now - timedelta(hours=4)
        deadline = self.now - timedelta(hours=2)
        handover = self.now - timedelta(hours=1)  # 1 hour late

        res = StudentReservation.objects.create(
            student_id='ST-1',
            student_name='Student 1',
            course_year_section='BSBA 1',
            email='s1@cba.edu',
            contact_number='09171111111',
            category=self.cat_av,
            asset=self.proj_1,
            requested_pickup=past_start,
            requested_return=deadline,
            purpose='Event',
            status=StudentReservation.Status.RELEASED,
            released_by=self.custodian_user,
            released_at=past_start,
            id_deposit_verified=True
        )

        student_services.record_guard_return(
            reservation=res,
            recorded_by=self.custodian_user,
            guard_returned_at=handover,
            guard_handover_details='Guard post handover'
        )
        res.refresh_from_db()

        self.assertTrue(res.is_overdue)
        self.assertAlmostEqual(res.overdue_duration.total_seconds(), 3600, delta=10)


class SecurityAndAccessControlTestCase(StudentReservationBaseTestCase):
    """Tests security rules, permission checks, lookup protection, and rate limiting."""

    def test_non_admin_cannot_perform_office_actions(self):
        """Faculty, Chairs, and unauthenticated users cannot approve, release, or inspect equipment."""
        res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Event'
        )

        with self.assertRaises(PermissionDenied):
            student_services.approve_reservation(res, self.proj_1, self.faculty_user)

        with self.assertRaises(PermissionDenied):
            student_services.approve_reservation(res, self.proj_1, self.chair_user)

        with self.assertRaises(PermissionDenied):
            student_services.approve_reservation(res, self.proj_1, None)

    def test_public_lookup_by_token_and_privacy_masking(self):
        """Public lookup requires valid lookup_token and masks student contact information."""
        res = student_services.submit_reservation(
            'ST-1', 'Maria Clara', 'BSBA 2-A', 'mariaclara@student.edu', '09171234567',
            self.cat_av, self.t_start, self.t_end, 'Report'
        )

        # Lookup by token succeeds
        found = student_services.get_reservation_by_token(res.lookup_token)
        self.assertEqual(found.pk, res.pk)

        # Invalid token fails
        with self.assertRaises(ValidationError):
            student_services.get_reservation_by_token('non-existent-random-token-xyz')

        # Contact masking test
        masked_email, masked_phone = mask_contact_info(res.email, res.contact_number)
        self.assertNotEqual(masked_email, res.email)
        self.assertIn('***', masked_email)
        self.assertNotEqual(masked_phone, res.contact_number)
        self.assertIn('****', masked_phone)

    def test_rate_limiting_prevents_excessive_submissions(self):
        """Rate limiting prevents more than 3 pending requests for the same student ID."""
        for i in range(3):
            student_services.submit_reservation(
                'ST-SPAM-1', f'Spam Student {i}', 'BSBA 1', f'spam{i}@cba.edu', '09170000000',
                self.cat_av, self.t_start + timedelta(days=i), self.t_end + timedelta(days=i), 'Purpose'
            )

        factory = RequestFactory()
        req = factory.post('/student-reservations/request/')

        with self.assertRaises(ValidationError) as ctx:
            check_submission_rate_limit(req, 'ST-SPAM-1')
        self.assertIn("already has 3 pending reservations", str(ctx.exception))

    def test_non_reservable_category_excluded_from_catalog(self):
        """Items in non-reservable categories cannot be reserved."""
        with self.assertRaises(ValidationError) as ctx:
            student_services.submit_reservation(
                'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
                self.cat_furniture, self.t_start, self.t_end, 'Need chairs'
            )
        self.assertIn("not currently available for reservations", str(ctx.exception))


class InvalidStatusTransitionsTestCase(StudentReservationBaseTestCase):
    """Tests that illegal or out-of-order lifecycle transitions are strictly rejected."""

    def test_cannot_release_pending_reservation(self):
        """A reservation must be in APPROVED status before it can be released."""
        res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Event'
        )
        with self.assertRaises(ValidationError):
            student_services.release_equipment(res, self.custodian_user, id_deposited=True)

    def test_cannot_return_unreleased_reservation(self):
        """A reservation must be in RELEASED status before it can be returned."""
        res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Event'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user)

        with self.assertRaises(ValidationError):
            student_services.return_equipment_to_office(
                res, self.custodian_user, Asset.Condition.GOOD
            )

    def test_cannot_inspect_direct_office_return(self):
        """Guard inspection is only valid for reservations in RETURNED_TO_GUARD status."""
        res = student_services.submit_reservation(
            'ST-1', 'Student 1', 'BSBA 1', 's1@cba.edu', '09171111111',
            self.cat_av, self.t_start, self.t_end, 'Event'
        )
        student_services.approve_reservation(res, self.proj_1, self.custodian_user)
        student_services.release_equipment(res, self.custodian_user, id_deposited=True)
        student_services.return_equipment_to_office(res, self.custodian_user, Asset.Condition.GOOD)

        with self.assertRaises(ValidationError):
            student_services.complete_inspection(res, self.custodian_user, Asset.Condition.GOOD)


class StudentReservationFrontendViewTestCase(StudentReservationBaseTestCase):
    """
    Focused tests for Phase 2A student-facing views, templates, validation, and HTMX endpoints:
    1. Catalog view with reservable assets and availability checking
    2. Availability checker HTMX endpoint
    3. Mobile-friendly reservation form (GET & POST)
    4. Confirmation screen and tracking token
    5. Status lookup view (HTML, HTMX partial, and JSON API)
    """

    def setUp(self):
        super().setUp()
        self.client = Client()

    def test_catalog_view_renders_properly(self):
        """Catalog displays reservable categories and unit counts while excluding non-reservable categories."""
        response = self.client.get('/student-reservations/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_reservations/catalog.html')
        self.assertContains(response, 'Audio-Visual')
        self.assertContains(response, '3 FREE')
        # Non-reservable category should not appear as a reservable card
        self.assertNotContains(response, 'Office Furniture')

    def test_check_availability_htmx_endpoint(self):
        """HTMX schedule availability checker returns live counts for requested timeslot."""
        pickup_str = self.t_start.strftime('%Y-%m-%dT%H:%M')
        return_str = self.t_end.strftime('%Y-%m-%dT%H:%M')

        # 1. Available check (all 3 projectors available)
        response = self.client.get(
            f'/student-reservations/check-availability/?pickup={pickup_str}&return={return_str}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_reservations/partials/_availability_result.html')
        self.assertContains(response, '3 FREE')

        # 2. Allocate and approve all 3 projectors for this timeslot
        for i, proj in enumerate([self.proj_1, self.proj_2, self.proj_3], start=1):
            r = student_services.submit_reservation(
                f'ST-TEST-{i}', f'Student {i}', 'BSBA 1', f'st{i}@cba.edu', '09170000000',
                self.cat_av, self.t_start, self.t_end, 'Event'
            )
            student_services.approve_reservation(r, proj, self.custodian_user)

        # 3. Check again: now 0 of 3 available (Fully Booked)
        response = self.client.get(
            f'/student-reservations/check-availability/?pickup={pickup_str}&return={return_str}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Fully Booked')

    def test_check_availability_validation_errors(self):
        """Availability checker displays errors on invalid timeslots."""
        # Return time before pickup time
        pickup_str = self.t_end.strftime('%Y-%m-%dT%H:%M')
        return_str = self.t_start.strftime('%Y-%m-%dT%H:%M')
        response = self.client.get(
            f'/student-reservations/check-availability/?pickup={pickup_str}&return={return_str}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Requested return time must be strictly after pickup time.')

    def test_reservation_form_get_and_post_submission(self):
        """Student reservation form renders properly and accepts valid submissions."""
        # 1. GET form
        response = self.client.get(f'/student-reservations/request/?category={self.cat_av.id}')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_reservations/reservation_form.html')
        self.assertContains(response, 'Physical School ID Custody Policy')

        # 2. POST valid submission
        post_data = {
            'student_id': '2024-99881',
            'student_name': 'Jose Rizal',
            'course_year_section': 'BSBA MM 4-A',
            'email': 'j.rizal@student.cba.edu',
            'contact_number': '09181234567',
            'category': self.cat_av.id,
            'equipment_type': 'HDMI Projector',
            'requested_pickup': (timezone.localtime() + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
            'requested_return': (timezone.localtime() + timedelta(hours=5)).strftime('%Y-%m-%dT%H:%M'),
            'purpose': 'Marketing thesis oral defense in AVR',
            'room_venue': 'AVR Hall',
        }
        post_resp = self.client.post('/student-reservations/request/', data=post_data)
        # Should redirect to confirmation page
        self.assertEqual(post_resp.status_code, 302)
        self.assertIn('/student-reservations/confirmed/', post_resp.url)

        res = StudentReservation.objects.get(student_id='2024-99881')
        self.assertEqual(res.status, StudentReservation.Status.PENDING)
        self.assertIsNotNone(res.lookup_token)

    def test_confirmation_page_renders_with_token(self):
        """Confirmation screen displays reservation token, summary, and next steps."""
        res = student_services.submit_reservation(
            '2024-55443', 'Andres Bonifacio', 'BSBA 3-B', 'a.bonifacio@cba.edu', '09191234567',
            self.cat_av, self.t_start, self.t_end, 'Leadership Seminar', 'Room 102'
        )
        response = self.client.get(f'/student-reservations/confirmed/{res.lookup_token}/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_reservations/confirmation.html')
        self.assertContains(response, res.lookup_token)
        self.assertContains(response, 'Andres Bonifacio')
        self.assertContains(response, 'What Happens Next?')

    def test_status_lookup_page_and_htmx_partial(self):
        """Status lookup renders full page and HTMX status card with privacy masking."""
        res = student_services.submit_reservation(
            '2024-11223', 'Apolinario Mabini', 'BSBA 2-A', 'mabini@cba.edu', '09179876543',
            self.cat_av, self.t_start, self.t_end, 'Research Presentation'
        )

        # 1. Empty lookup page
        response = self.client.get('/student-reservations/lookup/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_reservations/lookup.html')
        self.assertContains(response, 'Track Equipment Reservation')

        # 2. Lookup with token GET param
        response = self.client.get(f'/student-reservations/lookup/?token={res.lookup_token}')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Apolinario Mabini')
        self.assertContains(response, 'Pending Custodian Review')
        # Privacy masking: real email & phone are masked
        self.assertNotContains(response, 'mabini@cba.edu')
        self.assertNotContains(response, '09179876543')

        # 3. Direct lookup URL
        response = self.client.get(f'/student-reservations/lookup/{res.lookup_token}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Apolinario Mabini')

        # 4. HTMX partial request
        htmx_resp = self.client.get(
            f'/student-reservations/lookup/{res.lookup_token}/',
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(htmx_resp.status_code, 200)
        self.assertTemplateUsed(htmx_resp, 'student_reservations/partials/_status_card.html')

        # 5. Invalid token renders warning
        invalid_resp = self.client.get('/student-reservations/lookup/?token=invalid-random-token')
        self.assertEqual(invalid_resp.status_code, 200)
        self.assertContains(invalid_resp, 'Reservation Not Found')

    def test_multi_day_longer_reservation_request_allowed(self):
        """
        Valid multi-day reservation requests (e.g. 72-hour weekend event) are accepted without
        an unapproved 48-hour ceiling, while remaining strictly in PENDING status for manual Custodian review.
        """
        # Friday 1:00 PM to Monday 1:00 PM (72 hours)
        long_pickup = timezone.now() + timedelta(days=2)
        long_return = long_pickup + timedelta(hours=72)

        post_data = {
            'student_id': '2024-77889',
            'student_name': 'Melchora Aquino',
            'course_year_section': 'BSBA 4-C',
            'email': 'm.aquino@student.cba.edu',
            'contact_number': '09171239876',
            'category': self.cat_av.id,
            'equipment_type': 'Projector',
            'requested_pickup': long_pickup.strftime('%Y-%m-%dT%H:%M'),
            'requested_return': long_return.strftime('%Y-%m-%dT%H:%M'),
            'purpose': 'College Business Leadership Weekend Symposium',
            'room_venue': 'University Auditorium',
        }
        response = self.client.post('/student-reservations/request/', data=post_data)
        # Successfully accepted and redirected to confirmation (not rejected by 48-hour error)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/student-reservations/confirmed/', response.url)

        res = StudentReservation.objects.get(student_id='2024-77889')
        # Remains in PENDING status awaiting manual Custodian approval; not automatically approved
        self.assertEqual(res.status, StudentReservation.Status.PENDING)
        self.assertIsNone(res.asset)
        self.assertIsNone(res.reviewed_by)

    def test_check_availability_supports_multi_day_interval(self):
        """Availability checker supports intervals longer than 48 hours without error."""
        long_pickup = timezone.now() + timedelta(days=1)
        long_return = long_pickup + timedelta(hours=72)
        pickup_str = long_pickup.strftime('%Y-%m-%dT%H:%M')
        return_str = long_return.strftime('%Y-%m-%dT%H:%M')

        response = self.client.get(
            f'/student-reservations/check-availability/?pickup={pickup_str}&return={return_str}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'student_reservations/partials/_availability_result.html')
        self.assertNotContains(response, '48 consecutive hours')
        self.assertContains(response, '3 FREE')


class StudentPortalUXSimplificationTestCase(StudentReservationBaseTestCase):
    """
    Comprehensive regression tests for Phase 2A Student Portal UX Simplification:
    1. Mandatory inputs reduced (ID, Name, at least one contact method, Category, Pickup, Return, Purpose).
    2. Optional inputs (Course/Section, Venue, Model preference) can be empty.
    3. Purpose dropdown validation and conditional details.
    4. Contact method validation (email-only, phone-only, rejecting missing contact).
    5. Zero-stock category differentiation in catalog and availability checker.
    6. Sensible Manila schedule defaults.
    7. Phone-only and email-only confirmation and status lookup behavior.
    """

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.pickup_str = (timezone.localtime() + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')
        self.return_str = (timezone.localtime() + timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M')

        # Create zero-stock category (reservable, but 0 assets)
        self.cat_zero = AssetCategory.objects.create(
            code='DISP',
            name='Display Equipment',
            is_active=True,
            is_reservable=True
        )

    def test_submission_with_email_only(self):
        """Student can submit reservation using only an email address (no mobile number)."""
        post_data = {
            'student_id': '2024-11001',
            'student_name': 'Maria Clara',
            'course_year_section': '',
            'email': 'm.clara@student.cba.edu',
            'contact_number': '',
            'category': self.cat_av.id,
            'equipment_type': '',
            'requested_pickup': self.pickup_str,
            'requested_return': self.return_str,
            'purpose': 'Class Presentation / Reporting',
            'purpose_details': '',
            'room_venue': '',
        }
        response = self.client.post('/student-reservations/request/', data=post_data)
        self.assertEqual(response.status_code, 302)
        res = StudentReservation.objects.get(student_id='2024-11001')
        self.assertEqual(res.email, 'm.clara@student.cba.edu')
        self.assertEqual(res.contact_number, '')
        self.assertEqual(res.course_year_section, '')
        self.assertEqual(res.room_venue, '')
        self.assertEqual(res.equipment_type, '')
        self.assertEqual(res.purpose, 'Class Presentation / Reporting')

    def test_submission_with_phone_only(self):
        """Student can submit reservation using only a mobile number (no email address)."""
        post_data = {
            'student_id': '2024-11002',
            'student_name': 'Crisostomo Ibarra',
            'course_year_section': '',
            'email': '',
            'contact_number': '09171234567',
            'category': self.cat_av.id,
            'equipment_type': '',
            'requested_pickup': self.pickup_str,
            'requested_return': self.return_str,
            'purpose': 'Class Presentation / Reporting',
            'purpose_details': '',
            'room_venue': '',
        }
        response = self.client.post('/student-reservations/request/', data=post_data)
        self.assertEqual(response.status_code, 302)
        res = StudentReservation.objects.get(student_id='2024-11002')
        self.assertEqual(res.contact_number, '09171234567')
        self.assertEqual(res.email, '')

    def test_submission_fails_without_any_contact_method(self):
        """Submission is rejected when neither email nor mobile number is provided."""
        post_data = {
            'student_id': '2024-11003',
            'student_name': 'Elias Salome',
            'course_year_section': '',
            'email': '',
            'contact_number': '',
            'category': self.cat_av.id,
            'equipment_type': '',
            'requested_pickup': self.pickup_str,
            'requested_return': self.return_str,
            'purpose': 'Class Presentation / Reporting',
            'purpose_details': '',
            'room_venue': '',
        }
        response = self.client.post('/student-reservations/request/', data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please provide at least one contact method')

    def test_purpose_other_requires_details(self):
        """When 'Other' is chosen, purpose_details is required."""
        post_data = {
            'student_id': '2024-11004',
            'student_name': 'Basilio Sisa',
            'email': 'basilio@student.cba.edu',
            'category': self.cat_av.id,
            'requested_pickup': self.pickup_str,
            'requested_return': self.return_str,
            'purpose': 'Other',
            'purpose_details': '',
        }
        response = self.client.post('/student-reservations/request/', data=post_data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please briefly specify your activity purpose')

    def test_purpose_other_formats_properly_with_details(self):
        """When 'Other' is selected with details, stored purpose is 'Other: <details>'."""
        post_data = {
            'student_id': '2024-11005',
            'student_name': 'Simoun Ibarra',
            'email': 'simoun@student.cba.edu',
            'category': self.cat_av.id,
            'requested_pickup': self.pickup_str,
            'requested_return': self.return_str,
            'purpose': 'Other',
            'purpose_details': 'Inter-Collegiate Debate Championship',
        }
        response = self.client.post('/student-reservations/request/', data=post_data)
        self.assertEqual(response.status_code, 302)
        res = StudentReservation.objects.get(student_id='2024-11005')
        self.assertEqual(res.purpose, 'Other: Inter-Collegiate Debate Championship')

    def test_zero_stock_category_shows_not_currently_available(self):
        """Categories with 0 total assets display 'Not currently available' and disabled CTA."""
        response = self.client.get(
            f'/student-reservations/check-availability/?pickup={self.pickup_str}&return={self.return_str}'
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Display Equipment')
        self.assertContains(response, 'Not currently available')
        self.assertContains(response, 'ALL OUT')

    def test_confirmation_page_phone_only_user(self):
        """Phone-only user sees tracking token, copy button, mobile number, and no SMS promise."""
        res = student_services.submit_reservation(
            student_id='2024-11006',
            student_name='Isagani Rivera',
            course_year_section='',
            email='',
            contact_number='09191112233',
            category=self.cat_av,
            requested_pickup=timezone.localtime() + timedelta(hours=2),
            requested_return=timezone.localtime() + timedelta(hours=4),
            purpose='Class Presentation / Reporting'
        )
        response = self.client.get(f'/student-reservations/confirmed/{res.lookup_token}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Copy Token')
        self.assertContains(response, res.lookup_token)
        self.assertContains(response, '09191112233')
        self.assertContains(response, 'No automated SMS or email notification is sent')
        # Does not show empty course/section label
        self.assertNotContains(response, '<dt class="col-sm-4 text-secondary">Course &amp; Section:</dt>')

    def test_status_lookup_masks_email_and_phone_without_fallback_bug(self):
        """Status lookup renders masked contact without hardcoded '0917****' for email-only users."""
        res = student_services.submit_reservation(
            student_id='2024-11007',
            student_name='Paulita Gomez',
            course_year_section='',
            email='paulita.gomez@student.cba.edu',
            contact_number='',
            category=self.cat_av,
            requested_pickup=timezone.localtime() + timedelta(hours=2),
            requested_return=timezone.localtime() + timedelta(hours=4),
            purpose='Class Presentation / Reporting'
        )
        response = self.client.get(f'/student-reservations/lookup/{res.lookup_token}/')
        self.assertEqual(response.status_code, 200)
        # Should NOT contain hardcoded fallback 0917****
        self.assertNotContains(response, '0917****')
        self.assertContains(response, 'pa***z@student.cba.edu')

    def test_sensible_default_schedule_helper(self):
        """get_sensible_default_schedule() returns office hours on a weekday."""
        from apps.student_reservations.views import get_sensible_default_schedule
        pickup, ret = get_sensible_default_schedule()
        self.assertTrue(pickup < ret)
        # Weekday check: Monday (0) to Friday (4)
        self.assertIn(pickup.weekday(), [0, 1, 2, 3, 4])
        # Office hour check (between 8am and 5pm)
        self.assertGreaterEqual(pickup.hour, 8)
        self.assertLessEqual(ret.hour, 17)


class EquipmentTypeSelectionAndAllocationTestCase(StudentReservationBaseTestCase):
    """
    Comprehensive test suite for Phase 2A Equipment Type Selection & Allocation (Priority 1):
    - Normalized EquipmentType model constraints and category integrity
    - Server-side validation of category/type dependencies
    - Strict Custodian allocation enforcement (rejection of mismatches and unassigned units)
    - Legacy reservation backward compatibility
    - Dynamic availability filtering by specific equipment type
    - Equipment Type JSON API endpoint
    """

    def setUp(self):
        super().setUp()
        from apps.inventory.models import EquipmentType
        # Create Equipment Types under cat_av
        self.type_projector = EquipmentType.objects.create(
            category=self.cat_av,
            name='Multimedia Projector',
            description='LCD/DLP video projector',
            is_active=True
        )
        self.type_speaker = EquipmentType.objects.create(
            category=self.cat_av,
            name='Active Speaker',
            description='Portable sound system',
            is_active=True
        )

        # Create Category IT and Equipment Type under cat_it
        self.cat_it = AssetCategory.objects.create(
            code='IT',
            name='Information Technology',
            is_active=True,
            is_reservable=True
        )
        self.type_laptop = EquipmentType.objects.create(
            category=self.cat_it,
            name='Laptop Computer',
            description='Windows laptop',
            is_active=True
        )

        # Assets with assigned equipment types
        self.asset_proj1 = Asset.objects.create(
            property_number='PROP-PRJ-01',
            item_name='Epson Projector 1',
            category=self.cat_av,
            equipment_type=self.type_projector,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            is_reservable=True,
            department=self.dept_cba,
            current_location=self.loc_office,
            acquisition_cost=Decimal('25000.00'),
            acquisition_date=date(2025, 1, 1),
            created_by=self.custodian_user
        )
        self.asset_speaker1 = Asset.objects.create(
            property_number='PROP-SPK-01',
            item_name='Sony Speaker 1',
            category=self.cat_av,
            equipment_type=self.type_speaker,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            is_reservable=True,
            department=self.dept_cba,
            current_location=self.loc_office,
            acquisition_cost=Decimal('15000.00'),
            acquisition_date=date(2025, 1, 1),
            created_by=self.custodian_user
        )
        # Asset with unassigned equipment type (legacy inventory)
        self.asset_unassigned = Asset.objects.create(
            property_number='PROP-UNASSIGNED-01',
            item_name='Generic AV Device',
            category=self.cat_av,
            equipment_type=None,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            is_reservable=True,
            department=self.dept_cba,
            current_location=self.loc_office,
            acquisition_cost=Decimal('5000.00'),
            acquisition_date=date(2025, 1, 1),
            created_by=self.custodian_user
        )

    def test_equipment_type_uniqueness_and_category_integrity(self):
        """EquipmentType enforces uniqueness per category; Asset.clean() enforces category match."""
        from apps.inventory.models import EquipmentType
        from django.db import IntegrityError

        # Duplicate name under same category must be rejected by unique constraint
        from django.db import transaction
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                EquipmentType.objects.create(
                    category=self.cat_av,
                    name='Multimedia Projector'
                )

        # Same name under different category is permitted
        other_proj = EquipmentType.objects.create(
            category=self.cat_it,
            name='Multimedia Projector'
        )
        self.assertEqual(other_proj.name, 'Multimedia Projector')

        # Asset cannot be assigned an equipment type belonging to a different category
        invalid_asset = Asset(
            property_number='PROP-INVALID-01',
            item_name='Mismatched Asset',
            category=self.cat_av,
            equipment_type=self.type_laptop,  # Belongs to cat_it, not cat_av
            created_by=self.custodian_user
        )
        with self.assertRaises(ValidationError) as ctx:
            invalid_asset.clean()
        self.assertIn("does not match asset category", str(ctx.exception))

    def test_public_form_requires_equipment_type_when_category_has_types(self):
        """Form rejects submission without equipment_type_ref when category has active types."""
        from apps.student_reservations.forms import PublicStudentReservationForm
        form_data = {
            'student_id': '2023-11001',
            'student_name': 'Test Student',
            'email': 'student@cba.edu',
            'category': self.cat_av.id,
            'equipment_type_ref': '',  # Omitted
            'requested_pickup': (timezone.localtime() + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
            'requested_return': (timezone.localtime() + timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M'),
            'purpose': 'Class Presentation / Reporting',
        }
        form = PublicStudentReservationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('equipment_type_ref', form.errors)
        self.assertIn("Please select a specific equipment type", form.errors['equipment_type_ref'][0])

    def test_public_form_rejects_mismatched_category_equipment_type(self):
        """Form rejects equipment_type_ref that belongs to another category."""
        from apps.student_reservations.forms import PublicStudentReservationForm
        form_data = {
            'student_id': '2023-11002',
            'student_name': 'Test Student',
            'email': 'student@cba.edu',
            'category': self.cat_av.id,
            'equipment_type_ref': self.type_laptop.id,  # Laptop belongs to cat_it
            'requested_pickup': (timezone.localtime() + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M'),
            'requested_return': (timezone.localtime() + timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M'),
            'purpose': 'Class Presentation / Reporting',
        }
        form = PublicStudentReservationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('equipment_type_ref', form.errors)

    def test_submit_reservation_with_equipment_type_ref(self):
        """Submitting reservation with equipment_type_ref stores FK and populates text field."""
        res = student_services.submit_reservation(
            student_id='2023-11003',
            student_name='Clara Santos',
            course_year_section='BSBA 3-A',
            email='clara@cba.edu',
            contact_number='09171234567',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Class Presentation / Reporting',
            equipment_type_ref=self.type_projector
        )
        self.assertEqual(res.equipment_type_ref, self.type_projector)
        self.assertEqual(res.equipment_type, 'Multimedia Projector')

    def test_custodian_approval_succeeds_when_asset_type_matches(self):
        """Custodian approval succeeds when physical asset matches reservation equipment_type_ref."""
        res = student_services.submit_reservation(
            student_id='2023-11004',
            student_name='Basilio Rizal',
            course_year_section='BSBA 4-B',
            email='basilio@cba.edu',
            contact_number='09171234568',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Thesis Defense',
            equipment_type_ref=self.type_projector
        )
        approved_res = student_services.approve_reservation(
            reservation=res,
            asset=self.asset_proj1,
            reviewed_by=self.custodian_user
        )
        self.assertEqual(approved_res.status, StudentReservation.Status.APPROVED)
        self.assertEqual(approved_res.asset, self.asset_proj1)

    def test_custodian_approval_rejected_when_asset_has_different_type(self):
        """Custodian approval is rejected if asset has a different equipment type in the same category."""
        res = student_services.submit_reservation(
            student_id='2023-11005',
            student_name='Isagani Gomez',
            course_year_section='BSBA 2-A',
            email='isagani@cba.edu',
            contact_number='09171234569',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Seminar',
            equipment_type_ref=self.type_projector
        )
        # Attempting to allocate Speaker for a Projector reservation
        with self.assertRaises(ValidationError) as ctx:
            student_services.approve_reservation(
                reservation=res,
                asset=self.asset_speaker1,
                reviewed_by=self.custodian_user
            )
        self.assertIn("does not match requested equipment type", str(ctx.exception))
        self.assertIn("Multimedia Projector", str(ctx.exception))

    def test_custodian_approval_rejected_when_asset_has_no_type_assigned(self):
        """Custodian approval is rejected if physical asset has no assigned type when reservation requires one."""
        res = student_services.submit_reservation(
            student_id='2023-11006',
            student_name='Simoun Ibarra',
            course_year_section='BSBA 4-A',
            email='simoun@cba.edu',
            contact_number='09171234570',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Presentation',
            equipment_type_ref=self.type_projector
        )
        # Attempting to allocate unassigned physical asset
        with self.assertRaises(ValidationError) as ctx:
            student_services.approve_reservation(
                reservation=res,
                asset=self.asset_unassigned,
                reviewed_by=self.custodian_user
            )
        self.assertIn("physical asset has no assigned equipment type", str(ctx.exception))
        self.assertIn("Multimedia Projector", str(ctx.exception))

    def test_legacy_reservation_compatibility(self):
        """Legacy reservation without equipment_type_ref can be approved normally."""
        # Create legacy reservation directly without equipment_type_ref
        legacy_res = StudentReservation.objects.create(
            student_id='2022-99001',
            student_name='Legacy Student',
            course_year_section='BSBA 1-A',
            email='legacy@cba.edu',
            contact_number='09181112233',
            category=self.cat_av,
            equipment_type_ref=None,
            equipment_type='Multimedia Projector',
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Old Curriculum Reporting',
            lookup_token='LEGACYTOKEN' + '0' * 52
        )
        # Approving with asset having matching equipment_type or name
        approved = student_services.approve_reservation(
            reservation=legacy_res,
            asset=self.asset_proj1,
            reviewed_by=self.custodian_user
        )
        self.assertEqual(approved.status, StudentReservation.Status.APPROVED)
        self.assertEqual(approved.asset, self.asset_proj1)

    def test_availability_calculation_per_equipment_type(self):
        """Availability queries correctly filter by exact equipment_type_ref."""
        # Both Projector and Speaker are initially available
        avail_proj = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            equipment_type_ref=self.type_projector
        )
        self.assertEqual(len(avail_proj), 1)
        self.assertEqual(avail_proj[0], self.asset_proj1)

        avail_spk = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            equipment_type_ref=self.type_speaker
        )
        self.assertEqual(len(avail_spk), 1)
        self.assertEqual(avail_spk[0], self.asset_speaker1)

        # Book the Projector
        res = student_services.submit_reservation(
            student_id='2023-11007',
            student_name='Student User',
            course_year_section='BSBA 3-A',
            email='user@cba.edu',
            contact_number='09171234571',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Class Activity',
            equipment_type_ref=self.type_projector
        )
        student_services.approve_reservation(res, self.asset_proj1, self.custodian_user)

        # Projector availability is now 0 for that interval
        avail_proj_after = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            equipment_type_ref=self.type_projector
        )
        self.assertEqual(len(avail_proj_after), 0)

        # Speaker remains fully available (1 unit)
        avail_spk_after = student_services.get_available_assets_for_category(
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            equipment_type_ref=self.type_speaker
        )
        self.assertEqual(len(avail_spk_after), 1)

    def test_equipment_types_api_endpoint(self):
        """API endpoint /student-reservations/api/equipment-types/ returns active types for category."""
        url = reverse('student_reservations:api_equipment_types')
        response = self.client.get(f"{url}?category={self.cat_av.id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        type_names = [t['name'] for t in data['equipment_types']]
        self.assertIn('Multimedia Projector', type_names)
        self.assertIn('Active Speaker', type_names)
        self.assertNotIn('Laptop Computer', type_names)

    def test_custodian_list_view_access_and_rendering(self):
        """Custodian list view requires admin and displays student reservations table."""
        url = reverse('student_reservations:custodian_list')
        # Anonymous -> redirect to login
        resp_anon = self.client.get(url)
        self.assertEqual(resp_anon.status_code, 302)
        self.assertIn('/accounts/login/', resp_anon.url)

        # Faculty -> 403 Forbidden
        self.client.force_login(self.faculty_user)
        resp_faculty = self.client.get(url)
        self.assertEqual(resp_faculty.status_code, 403)

        # Custodian -> 200 OK with template
        self.client.force_login(self.custodian_user)
        resp_admin = self.client.get(url)
        self.assertEqual(resp_admin.status_code, 200)
        self.assertTemplateUsed(resp_admin, 'student_reservations/custodian_list.html')
        self.assertContains(resp_admin, 'Student Reservations Queue')

    def test_custodian_detail_view_approval_matching_asset(self):
        """Custodian can approve reservation with matching equipment type asset via detail view."""
        res = student_services.submit_reservation(
            student_id='2024-99001',
            student_name='Maria Santos',
            email='maria@cba.edu',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Class Presentation',
            equipment_type_ref=self.type_projector
        )
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})
        self.client.force_login(self.custodian_user)

        # GET detail view
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'student_reservations/custodian_detail.html')
        self.assertContains(resp, 'Multimedia Projector')

        # POST approve with matching asset
        post_resp = self.client.post(url, {
            'action': 'approve',
            'asset': self.asset_proj1.pk,
            'grace_period_minutes': 15,
            'remarks': 'Assigned Projector 1'
        })
        self.assertEqual(post_resp.status_code, 302)
        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.APPROVED)
        self.assertEqual(res.asset, self.asset_proj1)
        self.assertEqual(res.reviewed_by, self.custodian_user)

    def test_custodian_detail_view_approval_mismatched_asset_rejected(self):
        """Custodian cannot approve reservation with asset of mismatched equipment type."""
        res = student_services.submit_reservation(
            student_id='2024-99002',
            student_name='Jose Rizal',
            email='jose@cba.edu',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Class Presentation',
            equipment_type_ref=self.type_projector
        )
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})
        self.client.force_login(self.custodian_user)

        # POST approve with speaker asset (mismatched type)
        post_resp = self.client.post(url, {
            'action': 'approve',
            'asset': self.asset_speaker1.pk,
            'grace_period_minutes': 15
        })
        # Stays pending, does not approve
        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.PENDING)
        self.assertIsNone(res.asset)

    def test_lookup_instructions_43_character_copy(self):
        """Lookup screen instructions and placeholder specify 43 characters, not 32."""
        url = reverse('student_reservations:public_lookup_search')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '43-character')
        self.assertNotContains(resp, '32-character')


class StudentReservationCombinedUXRefinementTestCase(TestCase):
    """
    Focused verification for Student Reservation UX Refinement:
    1. Catalog-to-form selection carryover
    2. Direct access to reservation form expands selection editor
    3. Venue dropdown and Other custom specification
    4. Purpose dropdown concise options and Other specification
    5. Nine-digit student ID acceptance and placeholder
    6. Form resubmission retention on error
    7. Single primary Reserve CTA per equipment type in catalog
    """
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.dept = Department.objects.create(name='Business Administration', code='BA', is_active=True)
        self.cat = AssetCategory.objects.create(name='Projectors', code='PRJ', is_active=True, is_reservable=True)
        self.eq_type = EquipmentType.objects.create(category=self.cat, name='Classroom LCD Projector', is_active=True)
        self.brand = Brand.objects.create(name='Epson', is_active=True)
        self.asset = Asset.objects.create(
            asset_code='CBA-PRJ-TEST-1',
            item_name='Epson Projector 1',
            category=self.cat,
            equipment_type=self.eq_type,
            brand=self.brand,
            department=self.dept,
            status=Asset.Status.AVAILABLE,
            condition=Asset.Condition.GOOD,
            is_reservable=True
        )
        self.pickup_dt = timezone.localtime() + timedelta(hours=2)
        self.return_dt = timezone.localtime() + timedelta(hours=5)
        self.pickup_str = self.pickup_dt.strftime('%Y-%m-%dT%H:%M')
        self.return_str = self.return_dt.strftime('%Y-%m-%dT%H:%M')

    def test_catalog_selection_carryover_prefilled_state(self):
        """When equipment and times are selected from catalog, reservation form pre-populates and shows summary."""
        url = f"/student-reservations/request/?category={self.cat.id}&type={self.eq_type.id}&pickup={self.pickup_str}&return={self.return_str}"
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['selection_prefilled'])
        self.assertContains(resp, 'YOUR SELECTION')
        self.assertContains(resp, 'Classroom LCD Projector')
        self.assertContains(resp, 'Change equipment or schedule')

    def test_direct_request_access_expands_editor(self):
        """When student directly visits /request/ without catalog selection, editor is expanded."""
        resp = self.client.get('/student-reservations/request/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['selection_prefilled'])
        self.assertContains(resp, 'Choose equipment and schedule')
        self.assertContains(resp, '<details class="cba-selection-editor"')

    def test_venue_dropdown_standard_and_other_custom(self):
        """Standard venue selection stores standard name; Other requires and stores custom venue."""
        # 1. Standard venue selection
        post_data_standard = {
            'student_id': '202412345',
            'student_name': 'Juan Dela Cruz',
            'email': 'juan@student.cba.edu',
            'category': self.cat.id,
            'equipment_type_ref': self.eq_type.id,
            'requested_pickup': self.pickup_str,
            'requested_return': self.return_str,
            'purpose': 'Class presentation',
            'room_venue': 'CBA Room 4',
        }
        resp = self.client.post('/student-reservations/request/', post_data_standard)
        self.assertEqual(resp.status_code, 302)
        res1 = StudentReservation.objects.get(student_id='202412345')
        self.assertEqual(res1.room_venue, 'CBA Room 4')

        # 2. 'Other' venue with custom description
        post_data_other = {
            'student_id': '202412346',
            'student_name': 'Maria Clara',
            'email': 'maria@student.cba.edu',
            'category': self.cat.id,
            'equipment_type_ref': self.eq_type.id,
            'requested_pickup': self.pickup_str,
            'requested_return': self.return_str,
            'purpose': 'Thesis defense',
            'room_venue': 'Other',
            'room_venue_other': 'CBA AVR Amphitheater',
        }
        resp = self.client.post('/student-reservations/request/', post_data_other)
        self.assertEqual(resp.status_code, 302)
        res2 = StudentReservation.objects.get(student_id='202412346')
        self.assertEqual(res2.room_venue, 'CBA AVR Amphitheater')

        # 3. 'Other' venue without custom description fails
        post_data_other_empty = {
            'student_id': '202412347',
            'student_name': 'Crisostomo Ibarra',
            'email': 'ibarra@student.cba.edu',
            'category': self.cat.id,
            'equipment_type_ref': self.eq_type.id,
            'requested_pickup': self.pickup_str,
            'requested_return': self.return_str,
            'purpose': 'Class presentation',
            'room_venue': 'Other',
            'room_venue_other': '',
        }
        resp = self.client.post('/student-reservations/request/', post_data_other_empty)
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(resp, 'form', 'room_venue_other', 'Please specify your room or venue.')

    def test_purpose_dropdown_concise_options_and_other(self):
        """Concise purpose choices are stored directly; Other requires and stores details."""
        post_data = {
            'student_id': '202412348',
            'student_name': 'Elias Salome',
            'email': 'elias@student.cba.edu',
            'category': self.cat.id,
            'equipment_type_ref': self.eq_type.id,
            'requested_pickup': self.pickup_str,
            'requested_return': self.return_str,
            'purpose': 'Research presentation',
            'room_venue': 'CBA Room 1',
        }
        resp = self.client.post('/student-reservations/request/', post_data)
        self.assertEqual(resp.status_code, 302)
        res = StudentReservation.objects.get(student_id='202412348')
        self.assertEqual(res.purpose, 'Research presentation')

        # Other purpose requires details
        post_data_other_empty = {
            'student_id': '202412349',
            'student_name': 'Basilio Sisa',
            'email': 'basilio@student.cba.edu',
            'category': self.cat.id,
            'equipment_type_ref': self.eq_type.id,
            'requested_pickup': self.pickup_str,
            'requested_return': self.return_str,
            'purpose': 'Other',
            'purpose_details': '',
        }
        resp = self.client.post('/student-reservations/request/', post_data_other_empty)
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(resp, 'form', 'purpose_details', 'Please briefly specify your activity purpose.')

    def test_student_id_masked_placeholder_and_format(self):
        """Student ID field provides 2024XXXXX placeholder and validates."""
        resp = self.client.get('/student-reservations/request/')
        self.assertContains(resp, 'placeholder="2024XXXXX"')

    def test_single_reserve_cta_per_equipment_type_in_catalog(self):
        """When a category has equipment types, each type has one Reserve button and no duplicate category button."""
        resp = self.client.get(f'/student-reservations/check-availability/?pickup={self.pickup_str}&return={self.return_str}')
        self.assertEqual(resp.status_code, 200)
        # Concrete equipment type has Reserve button
        self.assertContains(resp, f'type={self.eq_type.id}')
        # Should not have duplicate category-wide button when equipment types are present
        self.assertNotContains(resp, f'Reserve {self.cat.name} &rarr;')


class StudentCatalogProjectorsPrimaryTestCase(TestCase):
    """
    Focused verification for Projectors as the Primary Student Equipment:
    1. Projectors category displayed first as featured full-width card when available.
    2. Primary CTA 'Reserve Projector' with correct carryover links.
    3. Secondary available equipment displayed under 'Other available equipment'.
    4. Unavailable or zero-stock equipment displayed under 'View unavailable equipment' disclosure.
    5. Graceful fallback when projectors are unavailable (no Reserve button) or missing.
    """
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.dept = Department.objects.create(name='Business Administration', code='BA', is_active=True)
        self.brand = Brand.objects.create(name='Epson', is_active=True)

        # 1. Primary: Projectors
        self.cat_proj = AssetCategory.objects.create(name='Projectors', code='PRJ', is_active=True, is_reservable=True)
        self.type_proj = EquipmentType.objects.create(category=self.cat_proj, name='Classroom LCD Projector', is_active=True)
        self.asset_proj = Asset.objects.create(
            asset_code='PRJ-TEST-01', item_name='Epson LCD Projector 1',
            category=self.cat_proj, equipment_type=self.type_proj, brand=self.brand,
            department=self.dept, status=Asset.Status.AVAILABLE, condition=Asset.Condition.GOOD, is_reservable=True
        )

        # 2. Secondary available: Audio-Visual (Microphones)
        self.cat_av = AssetCategory.objects.create(name='Audio-Visual Equipment', code='AV', is_active=True, is_reservable=True)
        self.type_mic = EquipmentType.objects.create(category=self.cat_av, name='Wireless Microphone Set', is_active=True)
        self.asset_mic = Asset.objects.create(
            asset_code='MIC-TEST-01', item_name='Shure Wireless Mic',
            category=self.cat_av, equipment_type=self.type_mic, brand=self.brand,
            department=self.dept, status=Asset.Status.AVAILABLE, condition=Asset.Condition.GOOD, is_reservable=True
        )

        # 3. Unavailable / Zero-stock: Appliances
        self.cat_app = AssetCategory.objects.create(name='Appliances', code='AP', is_active=True, is_reservable=True)

        self.pickup_dt = timezone.localtime() + timedelta(hours=2)
        self.return_dt = timezone.localtime() + timedelta(hours=5)
        self.pickup_str = self.pickup_dt.strftime('%Y-%m-%dT%H:%M')
        self.return_str = self.return_dt.strftime('%Y-%m-%dT%H:%M')

    def test_projector_featured_first_and_secondary_under_other_available(self):
        """Projector is featured first with prominent card; other available equipment is placed under 'Other available equipment'."""
        url = f'/student-reservations/check-availability/?pickup={self.pickup_str}&return={self.return_str}'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')

        # 1. Featured card presence & Primary CTA
        self.assertContains(resp, 'Primary Instructional Equipment')
        self.assertContains(resp, 'Projectors')
        self.assertContains(resp, 'Classroom LCD Projector')
        self.assertContains(resp, 'Reserve Projector')
        # URL parameters carryover
        expected_proj_link = f'category={self.cat_proj.id}&amp;type={self.type_proj.id}&amp;pickup={self.pickup_str}'
        self.assertIn(f'category={self.cat_proj.id}&type={self.type_proj.id}', content)

        # 2. Secondary available section
        self.assertContains(resp, 'Other available equipment')
        self.assertContains(resp, 'Audio-Visual Equipment')
        self.assertContains(resp, 'Wireless Microphone Set')

        # Ordering check: Projectors appears BEFORE 'Other available equipment'
        proj_idx = content.find('Projectors')
        other_idx = content.find('Other available equipment')
        self.assertNotEqual(proj_idx, -1)
        self.assertNotEqual(other_idx, -1)
        self.assertLess(proj_idx, other_idx, "Projectors must appear before 'Other available equipment'")

        # 3. Unavailable disclosure
        self.assertContains(resp, 'View unavailable equipment')
        self.assertContains(resp, 'Appliances')
        self.assertContains(resp, 'Not currently available')

        # Disclosure appears after secondary equipment
        unavail_idx = content.find('View unavailable equipment')
        self.assertNotEqual(unavail_idx, -1)
        self.assertLess(other_idx, unavail_idx, "'Other available equipment' must appear before unavailable disclosure")

    def test_initial_catalog_page_features_projector(self):
        """Initial catalog page load without query parameters also features projectors first."""
        resp = self.client.get('/student-reservations/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Primary Instructional Equipment')
        self.assertContains(resp, 'Reserve Projector')
        self.assertContains(resp, 'Other available equipment')
        self.assertContains(resp, 'View unavailable equipment')

    def test_projector_unavailable_hides_reserve_button(self):
        """When projectors are unavailable, featured card displays status but does not display Reserve button."""
        # Book the only projector
        self.asset_proj.status = Asset.Status.MAINTENANCE
        self.asset_proj.save()

        url = f'/student-reservations/check-availability/?pickup={self.pickup_str}&return={self.return_str}'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Still shows Projectors as featured category
        self.assertContains(resp, 'Projectors')
        self.assertContains(resp, 'Unavailable for this schedule')
        # Does NOT have Reserve button for projectors
        self.assertNotContains(resp, 'Reserve Projector')

    def test_projector_missing_graceful_fallback(self):
        """When no projector category exists, page renders other equipment gracefully without errors."""
        self.cat_proj.is_reservable = False
        self.cat_proj.save()

        resp = self.client.get('/student-reservations/')
        self.assertEqual(resp.status_code, 200)
        # Should not crash and should render remaining available equipment
        self.assertContains(resp, 'Audio-Visual Equipment')
        self.assertContains(resp, 'Wireless Microphone Set')
        self.assertNotContains(resp, 'Reserve Projector')


class ProjectorReleaseRegressionAndHandoverTestCase(StudentReservationBaseTestCase):
    """
    Focused regression and verification test suite for projector release and simplified handover UI:
    - Verifies release of approved reservation with allocated projector.
    - Permanent regression coverage for TypeError: release_equipment() got unexpected kwarg 'id_deposited'.
    - Enforces physical school ID verification and custody rules (service & view).
    - Verifies accurate physical asset status transition (AVAILABLE -> BORROWED).
    - Preserves condition snapshot and optional release notes.
    - Rejects unauthorized users.
    - Safely rejects duplicate release attempts without state corruption.
    - Confirms audit trail logging.
    - Confirms UI renders projector-specific vs generic wording and verification checklist.
    - Confirms Released status display after successful handover.
    """

    def setUp(self):
        super().setUp()
        self.t_start = timezone.now() + timedelta(hours=1)
        self.t_end = self.t_start + timedelta(hours=2)

        # Create specific projector equipment type and attach to self.proj_1
        self.type_projector = EquipmentType.objects.create(
            category=self.cat_av,
            name='Multimedia LCD Projector',
            is_active=True
        )
        self.proj_1.equipment_type = self.type_projector
        self.proj_1.save()

        # Audio equipment type for generic wording comparison
        self.type_mic = EquipmentType.objects.create(
            category=self.cat_av,
            name='Wireless Microphone',
            is_active=True
        )
        self.asset_mic = Asset.objects.create(
            item_name='Wireless Handheld Microphone',
            category=self.cat_av,
            department=self.dept_cba,
            equipment_type=self.type_mic,
            status=Asset.Status.AVAILABLE,
            condition=Asset.Condition.GOOD
        )

    def _create_approved_reservation(self, is_projector=True):
        eq_type = self.type_projector if is_projector else self.type_mic
        asset = self.proj_1 if is_projector else self.asset_mic
        res = student_services.submit_reservation(
            student_id='2024-55001',
            student_name='Juan Dela Cruz',
            course_year_section='BSBA 3-A',
            email='juan@student.cba.edu',
            contact_number='09171112233',
            category=self.cat_av,
            requested_pickup=self.t_start,
            requested_return=self.t_end,
            purpose='Instructional Presentation',
            equipment_type_ref=eq_type
        )
        approved = student_services.approve_reservation(
            reservation=res,
            asset=asset,
            reviewed_by=self.custodian_user,
            grace_period_minutes=20
        )
        return approved

    def test_approved_projector_reservation_released_via_view_regression(self):
        """
        Regression test: Submitting POST release on approved projector reservation
        must not raise TypeError (release_equipment unexpected kwarg 'id_deposited')
        and must transition reservation to RELEASED and asset to BORROWED.
        """
        res = self._create_approved_reservation(is_projector=True)
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})
        self.client.force_login(self.custodian_user)

        post_data = {
            'action': 'release',
            'condition_at_release': 'GOOD',
            'id_deposited': 'true',
            'remarks': 'Included HDMI cable, power adapter, and remote control',
        }
        resp = self.client.post(url, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.RELEASED)
        self.assertEqual(res.asset, self.proj_1)
        self.assertEqual(res.released_by, self.custodian_user)
        self.assertIsNotNone(res.released_at)
        self.assertEqual(res.condition_at_release, Asset.Condition.GOOD)
        self.assertIn('Included HDMI cable', res.remarks)

        # School ID custody verified
        self.assertTrue(res.id_deposit_verified)
        self.assertIsNotNone(res.id_deposited_at)
        self.assertTrue(res.is_id_in_custody)

        # Asset status updated
        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.BORROWED)

        # Success message displayed
        self.assertContains(resp, f"Projector allocated for reservation #{res.pk} marked as RELEASED")

    def test_service_release_equipment_accepts_id_deposited_kwarg(self):
        """Service release_equipment accepts id_deposited as a kwarg without TypeError."""
        res = self._create_approved_reservation(is_projector=True)
        released = student_services.release_equipment(
            reservation=res,
            released_by=self.custodian_user,
            condition_at_release=Asset.Condition.GOOD,
            id_deposited=True,
            remarks='Service test note'
        )
        self.assertEqual(released.status, StudentReservation.Status.RELEASED)
        self.assertTrue(released.id_deposit_verified)

    def test_service_release_equipment_rejects_missing_id_deposit(self):
        """Service release_equipment raises ValidationError if id_deposited is False."""
        res = self._create_approved_reservation(is_projector=True)
        with self.assertRaises(ValidationError) as ctx:
            student_services.release_equipment(
                reservation=res,
                released_by=self.custodian_user,
                condition_at_release=Asset.Condition.GOOD,
                id_deposited=False
            )
        self.assertIn("Student's physical school ID must be verified and deposited", str(ctx.exception))
        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.APPROVED)
        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.AVAILABLE)

    def test_service_release_equipment_rejects_omitted_id_deposited(self):
        """Service release_equipment raises ValidationError fail-closed when id_deposited argument is omitted."""
        res = self._create_approved_reservation(is_projector=True)
        with self.assertRaises(ValidationError) as ctx:
            student_services.release_equipment(
                reservation=res,
                released_by=self.custodian_user,
                condition_at_release=Asset.Condition.GOOD
                # id_deposited is deliberately omitted to test fail-closed default
            )
        self.assertIn("Student's physical school ID must be verified and deposited", str(ctx.exception))
        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.APPROVED)
        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.AVAILABLE)

    def test_view_release_equipment_rejects_missing_id_deposit(self):
        """View release action rejects submission when school ID deposit is unchecked."""
        res = self._create_approved_reservation(is_projector=True)
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})
        self.client.force_login(self.custodian_user)

        # Post without id_deposited checkbox
        resp = self.client.post(url, {
            'action': 'release',
            'condition_at_release': 'GOOD',
            'remarks': 'Testing missing ID'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Failed to release: student ID must be deposited.")

        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.APPROVED)
        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.AVAILABLE)

    def test_view_release_equipment_rejects_unserviceable_condition(self):
        """View release action rejects submission when condition at release is UNSERVICEABLE."""
        res = self._create_approved_reservation(is_projector=True)
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})
        self.client.force_login(self.custodian_user)

        resp = self.client.post(url, {
            'action': 'release',
            'condition_at_release': 'UNSERVICEABLE',
            'id_deposited': 'true',
            'remarks': 'Testing unserviceable condition'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Failed to release: please correct the release form errors.")

        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.APPROVED)
        self.proj_1.refresh_from_db()
        self.assertEqual(self.proj_1.status, Asset.Status.AVAILABLE)

    def test_unauthorized_user_cannot_release_equipment(self):
        """Non-custodian users cannot release equipment via the detail view."""
        res = self._create_approved_reservation(is_projector=True)
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})
        self.client.force_login(self.faculty_user)

        resp = self.client.post(url, {
            'action': 'release',
            'condition_at_release': 'GOOD',
            'id_deposited': 'true'
        })
        # Dispatched mixin raises PermissionDenied (403)
        self.assertEqual(resp.status_code, 403)

        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.APPROVED)

    def test_duplicate_release_attempt_safely_rejected(self):
        """Duplicate release attempts are rejected safely without state corruption."""
        res = self._create_approved_reservation(is_projector=True)
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})
        self.client.force_login(self.custodian_user)

        # First release succeeds
        resp1 = self.client.post(url, {
            'action': 'release',
            'condition_at_release': 'GOOD',
            'id_deposited': 'true'
        }, follow=True)
        self.assertEqual(resp1.status_code, 200)
        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.RELEASED)

        # Second release attempt on already released reservation
        resp2 = self.client.post(url, {
            'action': 'release',
            'condition_at_release': 'GOOD',
            'id_deposited': 'true'
        }, follow=True)
        self.assertEqual(resp2.status_code, 200)
        self.assertContains(resp2, "Equipment must be in APPROVED status before release")

        # Reservation remains in consistent RELEASED state
        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.RELEASED)

    def test_audit_log_recorded_on_release(self):
        """Audit trail accurately records release event with asset code and custody status."""
        from apps.audit.models import AuditLog
        res = self._create_approved_reservation(is_projector=True)
        student_services.release_equipment(
            reservation=res,
            released_by=self.custodian_user,
            condition_at_release=Asset.Condition.GOOD,
            id_deposited=True,
            remarks='Audit test'
        )
        logs = AuditLog.objects.filter(
            model_name='StudentReservation',
            object_id=str(res.pk),
            action='STUDENT_RESERVATION_RELEASED'
        )
        self.assertTrue(logs.exists())
        log = logs.first()
        self.assertEqual(log.user, self.custodian_user)
        self.assertEqual(log.changes.get('asset_code'), self.proj_1.asset_code)
        self.assertEqual(log.changes.get('condition_at_release'), Asset.Condition.GOOD)
        self.assertTrue(log.changes.get('id_deposited'))

    def test_ui_renders_projector_specific_wording_and_checklist(self):
        """GET detail view renders 'Confirm & Release Projector' and checklist for projectors."""
        res = self._create_approved_reservation(is_projector=True)
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})
        self.client.force_login(self.custodian_user)

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Confirm &amp; Release Projector')
        self.assertContains(resp, 'Release Projector Handover')
        self.assertContains(resp, 'Pickup Verification Checklist')
        self.assertContains(resp, 'Assigned Projector')
        self.assertContains(resp, self.proj_1.asset_code)
        self.assertContains(resp, 'Add optional release notes')

    def test_ui_renders_generic_wording_for_non_projectors(self):
        """GET detail view renders 'Confirm & Release Equipment' for non-projectors."""
        res = self._create_approved_reservation(is_projector=False)
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})
        self.client.force_login(self.custodian_user)

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Confirm &amp; Release Equipment')
        self.assertContains(resp, 'Release Equipment Handover')
        self.assertNotContains(resp, 'Confirm &amp; Release Projector')

    def test_ui_renders_released_status_after_successful_handover(self):
        """After release, detail view displays Released status badge and custody handover details."""
        res = self._create_approved_reservation(is_projector=True)
        student_services.release_equipment(
            reservation=res,
            released_by=self.custodian_user,
            condition_at_release=Asset.Condition.GOOD,
            id_deposited=True
        )
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})
        self.client.force_login(self.custodian_user)

        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'RELEASED &bull; IN USE')
        self.assertContains(resp, 'Equipment Successfully Released')
        self.assertContains(resp, 'Handover Completed')
        self.assertContains(resp, 'Released By Staff')


# Demonstration Data Seed Management Command Tests
from .test_seed_demo_equipment import SeedDemoEquipmentHardenedTestCase




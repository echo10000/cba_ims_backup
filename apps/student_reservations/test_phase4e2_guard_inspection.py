from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.inventory.models import AssetCategory, EquipmentType, Brand, Asset
from apps.organizations.models import Department, Location
from apps.student_reservations.models import StudentReservation

User = get_user_model()


class GuardInspectionAndIDCollectionTests(TestCase):
    """
    Focused regression tests for Phase 4E2: Guard Inspection and School ID Collection Workflow.
    Tests real authenticated Django views through HTTP POST and GET requests.

    Scenarios covered:
    1. Admin can inspect a guard-returned reservation.
    2. Inspection transitions RETURNED_TO_GUARD to RETURNED.
    3. GOOD inspection restores AVAILABLE status.
    4. UNSERVICEABLE inspection marks the asset DAMAGED.
    5. Inspection audit event is recorded (STUDENT_RESERVATION_INSPECTED).
    6. School ID remains in custody when not collected.
    7. ID collection can be recorded separately after inspection.
    8. Separate ID collection creates the expected audit event (STUDENT_ID_COLLECTED).
    9. Direct office returns with an uncollected ID support later collection.
    10. Duplicate inspections and duplicate ID collections fail safely.
    11. Invalid inspection condition and missing confirmation are rejected.
    12. Faculty and anonymous users cannot perform these operations.
    13. Awaiting Inspection queue filter displays the correct records.
    14. Existing Office Return and Guard Handover workflows still pass.
    """

    def setUp(self):
        self.client = Client()

        # Users
        self.admin_user = User.objects.create_user(
            username='custodian_admin_e2',
            email='custodian_e2@cba.edu',
            password='Password123!',
            role='ADMIN',
            is_staff=True
        )
        self.faculty_user = User.objects.create_user(
            username='faculty_member_e2',
            email='faculty_e2@cba.edu',
            password='Password123!',
            role='FACULTY'
        )

        # Department & Location
        self.dept = Department.objects.create(code='CBA', name='College of Business Administration')
        self.loc = Location.objects.create(name='Property Office', department=self.dept)

        # Category, Brand, Equipment Type
        self.cat_proj = AssetCategory.objects.create(
            name='Projectors',
            code='PRJ',
            is_reservable=True
        )
        self.brand = Brand.objects.create(name='Epson')
        self.eq_type = EquipmentType.objects.create(
            category=self.cat_proj,
            name='Classroom LCD Projector',
            is_active=True
        )

    def _create_asset(self, code='PRJ-E2-001', status=Asset.Status.AVAILABLE, condition=Asset.Condition.GOOD):
        return Asset.objects.create(
            asset_code=code,
            item_name='Epson EB-X06 Projector',
            category=self.cat_proj,
            equipment_type=self.eq_type,
            brand=self.brand,
            department=self.dept,
            current_location=self.loc,
            status=status,
            condition=condition,
            is_reservable=True
        )

    def _create_guard_returned_reservation(self, asset=None, student_name='Clara Santos'):
        if not asset:
            asset = self._create_asset(code=f'PRJ-E2-{StudentReservation.objects.count() + 1:03d}')

        now = timezone.now()
        res = StudentReservation.objects.create(
            student_id='202410991',
            student_name=student_name,
            course_year_section='BSBA 4-A',
            email='clara.santos@cba.edu',
            contact_number='09179998888',
            category=self.cat_proj,
            equipment_type_ref=self.eq_type,
            equipment_type='Classroom LCD Projector',
            requested_pickup=now - timedelta(hours=4),
            requested_return=now - timedelta(hours=1),
            purpose='Marketing Strategy Presentation',
            room_venue='CBA Room 201',
            status=StudentReservation.Status.RETURNED_TO_GUARD,
            asset=asset,
            released_by=self.admin_user,
            released_at=now - timedelta(hours=4),
            condition_at_release=Asset.Condition.GOOD,
            id_deposit_verified=True,
            id_deposited_at=now - timedelta(hours=4),
            id_collected_at=None,
            guard_returned_at=now - timedelta(minutes=45),
            guard_handover_details='Security Guard Mendoza - Gate 2 Guardhouse Logbook #112',
            guard_recorded_by=self.admin_user,
            guard_recorded_at=now - timedelta(minutes=30),
            remarks='Returned after hours to security guard on duty.'
        )

        asset.status = Asset.Status.BORROWED
        asset.save()
        return res, asset

    def _create_released_reservation(self, asset=None, student_name='Marco Diaz'):
        if not asset:
            asset = self._create_asset(code=f'PRJ-E2-{StudentReservation.objects.count() + 1:03d}')

        now = timezone.now()
        res = StudentReservation.objects.create(
            student_id='202410992',
            student_name=student_name,
            course_year_section='BSBA 2-B',
            email='marco.diaz@cba.edu',
            contact_number='09171112222',
            category=self.cat_proj,
            equipment_type_ref=self.eq_type,
            equipment_type='Classroom LCD Projector',
            requested_pickup=now - timedelta(hours=2),
            requested_return=now + timedelta(hours=2),
            purpose='Finance Committee Review',
            room_venue='CBA Audio-Visual Room',
            status=StudentReservation.Status.RELEASED,
            asset=asset,
            released_by=self.admin_user,
            released_at=now - timedelta(hours=2),
            condition_at_release=Asset.Condition.GOOD,
            id_deposit_verified=True,
            id_deposited_at=now - timedelta(hours=2),
            id_collected_at=None,
        )

        asset.status = Asset.Status.BORROWED
        asset.save()
        return res, asset

    def test_01_to_06_admin_inspect_guard_return_good_condition_id_in_custody(self):
        """
        Scenarios 1, 2, 3, 5, 6:
        1. Admin inspects guard-returned reservation.
        2. Status transitions RETURNED_TO_GUARD -> RETURNED.
        3. GOOD inspection restores AVAILABLE status.
        5. Inspection audit event (STUDENT_RESERVATION_INSPECTED) recorded.
        6. School ID remains in custody when id_collected_now=False.
        """
        self.client.force_login(self.admin_user)
        res, asset = self._create_guard_returned_reservation()
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})

        post_data = {
            'action': 'inspect_guard',
            'condition_at_return': Asset.Condition.GOOD,
            'inspection_remarks': 'Inspected: projector lens clean, tested power and HDMI port operational.',
            'id_collected_now': 'false'
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, url)

        res.refresh_from_db()
        asset.refresh_from_db()

        # Scenario 2: RETURNED status
        self.assertEqual(res.status, StudentReservation.Status.RETURNED)
        self.assertEqual(res.cba_inspected_by, self.admin_user)
        self.assertIsNotNone(res.cba_inspected_at)
        self.assertEqual(res.returned_to, self.admin_user)
        self.assertEqual(res.condition_at_return, Asset.Condition.GOOD)
        self.assertIn('projector lens clean', res.return_remarks)

        # Scenario 3: Asset restored to AVAILABLE
        self.assertEqual(asset.status, Asset.Status.AVAILABLE)
        self.assertEqual(asset.condition, Asset.Condition.GOOD)

        # Scenario 5: AuditLog created
        audit_entry = AuditLog.objects.filter(
            action='STUDENT_RESERVATION_INSPECTED',
            object_id=str(res.pk)
        ).first()
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry.user, self.admin_user)
        self.assertEqual(audit_entry.changes.get('resulting_asset_status'), Asset.Status.AVAILABLE)
        self.assertFalse(audit_entry.changes.get('id_collected'))

        # Scenario 6: ID remains in custody
        self.assertTrue(res.is_id_in_custody)
        self.assertIsNone(res.id_collected_at)

    def test_04_unserviceable_inspection_marks_asset_damaged(self):
        """
        Scenario 4: UNSERVICEABLE inspection transitions reservation to RETURNED,
        and marks the physical asset DAMAGED (not AVAILABLE).
        """
        self.client.force_login(self.admin_user)
        res, asset = self._create_guard_returned_reservation()
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})

        post_data = {
            'action': 'inspect_guard',
            'condition_at_return': Asset.Condition.UNSERVICEABLE,
            'inspection_remarks': 'Hardware broken: projector fan failure, overheating within 2 minutes.',
            'id_collected_now': 'false'
        }
        response = self.client.post(url, post_data)
        self.assertEqual(response.status_code, 302)

        res.refresh_from_db()
        asset.refresh_from_db()

        self.assertEqual(res.status, StudentReservation.Status.RETURNED)
        self.assertEqual(res.condition_at_return, Asset.Condition.UNSERVICEABLE)

        # Crucial: asset is DAMAGED, not AVAILABLE
        self.assertEqual(asset.status, Asset.Status.DAMAGED)
        self.assertEqual(asset.condition, Asset.Condition.UNSERVICEABLE)

    def test_07_and_08_separate_id_collection_lifecycle(self):
        """
        Scenarios 7 & 8:
        7. Physical School ID collection can be recorded separately after inspection.
        8. Creates expected audit event (STUDENT_ID_COLLECTED).
        """
        self.client.force_login(self.admin_user)
        res, _ = self._create_guard_returned_reservation()
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})

        # 1. Inspect first without collecting ID
        self.client.post(url, {
            'action': 'inspect_guard',
            'condition_at_return': Asset.Condition.GOOD,
            'inspection_remarks': 'Equipment intact.',
            'id_collected_now': 'false'
        })
        res.refresh_from_db()
        self.assertTrue(res.is_id_in_custody)

        # 2. Student returns later to retrieve ID
        collect_data = {
            'action': 'collect_id',
            'confirm_handed_back': 'true',
            'remarks': 'Student Clara Santos presented registration form and signed ID custody log.'
        }
        response = self.client.post(url, collect_data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, url)

        res.refresh_from_db()

        # Scenario 7: ID custody cleared
        self.assertFalse(res.is_id_in_custody)
        self.assertIsNotNone(res.id_collected_at)
        self.assertEqual(res.id_returned_by, self.admin_user)
        self.assertIn('Clara Santos', res.id_collection_remarks)

        # Scenario 8: Audit event recorded
        audit_entry = AuditLog.objects.filter(
            action='STUDENT_ID_COLLECTED',
            object_id=str(res.pk)
        ).first()
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry.user, self.admin_user)
        self.assertEqual(audit_entry.changes.get('student_name'), res.student_name)
        self.assertEqual(audit_entry.changes.get('student_id'), res.student_id)

    def test_09_direct_office_return_with_uncollected_id_supports_later_collection(self):
        """
        Scenario 9: Direct office return where ID was not collected immediately supports
        subsequent physical ID collection.
        """
        self.client.force_login(self.admin_user)
        res, asset = self._create_released_reservation()
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})

        # Return to office with id_collected_now=False
        resp_ret = self.client.post(url, {
            'action': 'return_office',
            'condition_at_return': Asset.Condition.GOOD,
            'id_collected_now': 'false',
            'return_remarks': 'Student returned equipment but left without ID.'
        })
        self.assertEqual(resp_ret.status_code, 302)

        res.refresh_from_db()
        asset.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.RETURNED)
        self.assertEqual(asset.status, Asset.Status.AVAILABLE)
        self.assertTrue(res.is_id_in_custody)

        # Later, student retrieves ID
        resp_coll = self.client.post(url, {
            'action': 'collect_id',
            'confirm_handed_back': 'true',
            'remarks': 'Handed back School ID to student Marco Diaz.'
        })
        self.assertEqual(resp_coll.status_code, 302)

        res.refresh_from_db()
        self.assertFalse(res.is_id_in_custody)
        self.assertIsNotNone(res.id_collected_at)
        self.assertEqual(res.id_returned_by, self.admin_user)

    def test_10_duplicate_or_invalid_inspections_and_collections_fail_safely(self):
        """
        Scenario 10: Duplicate inspections and duplicate ID collections fail safely
        without corrupting data.
        """
        self.client.force_login(self.admin_user)
        res, _ = self._create_guard_returned_reservation()
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})

        # 1. Complete inspection
        self.client.post(url, {
            'action': 'inspect_guard',
            'condition_at_return': Asset.Condition.GOOD,
            'id_collected_now': 'false'
        })
        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.RETURNED)

        # 2. Attempt duplicate inspection on already RETURNED reservation
        resp_dup_inspect = self.client.post(url, {
            'action': 'inspect_guard',
            'condition_at_return': Asset.Condition.GOOD,
            'id_collected_now': 'false'
        }, follow=True)
        self.assertEqual(resp_dup_inspect.status_code, 200)
        self.assertContains(resp_dup_inspect, "Cannot complete inspection")

        # 3. Collect ID
        self.client.post(url, {
            'action': 'collect_id',
            'confirm_handed_back': 'true',
            'remarks': 'First collection'
        })
        res.refresh_from_db()
        self.assertFalse(res.is_id_in_custody)

        # 4. Attempt duplicate ID collection on already collected ID
        resp_dup_id = self.client.post(url, {
            'action': 'collect_id',
            'confirm_handed_back': 'true',
            'remarks': 'Duplicate collection attempt'
        }, follow=True)
        self.assertEqual(resp_dup_id.status_code, 200)
        self.assertContains(resp_dup_id, "School ID was already collected")

        # 5. Attempt ID collection on a RELEASED reservation (before return)
        res_rel, _ = self._create_released_reservation()
        url_rel = reverse('student_reservations:custodian_detail', kwargs={'pk': res_rel.pk})
        resp_early_id = self.client.post(url_rel, {
            'action': 'collect_id',
            'confirm_handed_back': 'true'
        }, follow=True)
        self.assertEqual(resp_early_id.status_code, 200)
        self.assertContains(resp_early_id, "School ID collection can only be recorded after equipment return has been completed")

    def test_11_invalid_inspection_condition_and_unconfirmed_collection_rejected(self):
        """
        Scenario 11: Invalid inspection condition is rejected; ID collection without
        confirmation checkbox is rejected.
        """
        self.client.force_login(self.admin_user)
        res, _ = self._create_guard_returned_reservation()
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})

        # 1. Invalid condition on inspection
        resp_bad_cond = self.client.post(url, {
            'action': 'inspect_guard',
            'condition_at_return': '',
            'id_collected_now': 'false'
        })
        self.assertEqual(resp_bad_cond.status_code, 200)
        self.assertContains(resp_bad_cond, "Failed to complete inspection")
        res.refresh_from_db()
        self.assertEqual(res.status, StudentReservation.Status.RETURNED_TO_GUARD)

        # Inspect validly
        self.client.post(url, {
            'action': 'inspect_guard',
            'condition_at_return': Asset.Condition.GOOD,
            'id_collected_now': 'false'
        })
        res.refresh_from_db()

        # 2. Attempt collect_id without checking confirm_handed_back
        resp_no_confirm = self.client.post(url, {
            'action': 'collect_id',
            'remarks': 'Forgot to check confirmation box'
        })
        self.assertEqual(resp_no_confirm.status_code, 200)
        self.assertContains(resp_no_confirm, "Failed to record School ID collection: confirmation is required")
        res.refresh_from_db()
        self.assertTrue(res.is_id_in_custody)

    def test_12_unauthorized_faculty_and_anonymous_cannot_perform_operations(self):
        """
        Scenario 12: Faculty users receive 403 Forbidden; anonymous users are redirected to login.
        """
        res, _ = self._create_guard_returned_reservation()
        url = reverse('student_reservations:custodian_detail', kwargs={'pk': res.pk})

        # Anonymous user -> redirected to login
        resp_anon_inspect = self.client.post(url, {'action': 'inspect_guard', 'condition_at_return': 'GOOD'})
        self.assertEqual(resp_anon_inspect.status_code, 302)
        self.assertIn('/accounts/login/', resp_anon_inspect.url)

        resp_anon_collect = self.client.post(url, {'action': 'collect_id', 'confirm_handed_back': 'true'})
        self.assertEqual(resp_anon_collect.status_code, 302)
        self.assertIn('/accounts/login/', resp_anon_collect.url)

        # Faculty user -> 403 Forbidden
        self.client.force_login(self.faculty_user)
        resp_fac_inspect = self.client.post(url, {'action': 'inspect_guard', 'condition_at_return': 'GOOD'})
        self.assertEqual(resp_fac_inspect.status_code, 403)

        resp_fac_collect = self.client.post(url, {'action': 'collect_id', 'confirm_handed_back': 'true'})
        self.assertEqual(resp_fac_collect.status_code, 403)

    def test_13_awaiting_inspection_queue_filter_displays_correct_records(self):
        """
        Scenario 13: Staff queue filter 'Awaiting Inspection' displays only RETURNED_TO_GUARD records.
        """
        self.client.force_login(self.admin_user)
        res_guard, _ = self._create_guard_returned_reservation(student_name='Guard Returned Student')
        res_rel, _ = self._create_released_reservation(student_name='Released Active Student')

        queue_url = reverse('student_reservations:custodian_list')
        filter_url = f"{queue_url}?status=RETURNED_TO_GUARD"

        response = self.client.get(filter_url)
        self.assertEqual(response.status_code, 200)

        # Must display the guard-returned reservation
        self.assertContains(response, 'Guard Returned Student')
        self.assertContains(response, 'AWAITING INSPECTION')

        # Must NOT display the released reservation in this filtered view
        self.assertNotContains(response, 'Released Active Student')

        # Must include the filter count
        self.assertIn('awaiting_inspection_count', response.context)
        self.assertGreaterEqual(response.context['awaiting_inspection_count'], 1)

    def test_14_existing_office_return_and_guard_handover_still_pass(self):
        """
        Scenario 14: Verifies existing office return and guard handover workflows remain
        completely intact without regressions.
        """
        self.client.force_login(self.admin_user)

        # Office return path
        res_off, asset_off = self._create_released_reservation()
        url_off = reverse('student_reservations:custodian_detail', kwargs={'pk': res_off.pk})
        resp_off = self.client.post(url_off, {
            'action': 'return_office',
            'condition_at_return': Asset.Condition.GOOD,
            'id_collected_now': 'true',
            'return_remarks': 'Office return regression check.'
        })
        self.assertEqual(resp_off.status_code, 302)
        res_off.refresh_from_db()
        asset_off.refresh_from_db()
        self.assertEqual(res_off.status, StudentReservation.Status.RETURNED)
        self.assertEqual(asset_off.status, Asset.Status.AVAILABLE)

        # Guard handover path
        res_gd, asset_gd = self._create_released_reservation()
        url_gd = reverse('student_reservations:custodian_detail', kwargs={'pk': res_gd.pk})
        local_now = timezone.localtime()
        guard_time = (local_now - timedelta(minutes=15)).strftime('%Y-%m-%dT%H:%M')
        resp_gd = self.client.post(url_gd, {
            'action': 'return_guard',
            'guard_returned_at': guard_time,
            'guard_handover_details': 'Guard Handover regression check.'
        })
        self.assertEqual(resp_gd.status_code, 302)
        res_gd.refresh_from_db()
        asset_gd.refresh_from_db()
        self.assertEqual(res_gd.status, StudentReservation.Status.RETURNED_TO_GUARD)
        self.assertEqual(asset_gd.status, Asset.Status.BORROWED)

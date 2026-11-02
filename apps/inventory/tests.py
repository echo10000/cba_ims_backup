from django.test import TestCase, Client
from django.urls import reverse
from django.core.exceptions import ValidationError
from datetime import date
from decimal import Decimal
from apps.accounts.models import User
from apps.assignments.models import AssetAssignment
from apps.organizations.models import Department, Location, Employee
from apps.audit.models import AuditLog
from .models import AssetCategory, Brand, Asset


class InventoryModelTests(TestCase):
    def setUp(self):
        self.dept = Department.objects.create(name='Management', code='MGT')
        self.loc = Location.objects.create(name='Room 101', department=self.dept)
        self.category = AssetCategory.objects.create(name='Information Technology', code='IT')
        self.brand = Brand.objects.create(name='Dell')

    def test_category_and_brand_str(self):
        self.assertEqual(str(self.category), 'Information Technology')
        self.assertEqual(str(self.brand), 'Dell')

    def test_asset_code_auto_generation(self):
        asset1 = Asset.objects.create(
            item_name='Latitude 5420 Laptop',
            category=self.category,
            brand=self.brand,
            department=self.dept,
            current_location=self.loc,
        )
        self.assertEqual(asset1.asset_code, 'CBA-IT-00001')

        asset2 = Asset.objects.create(
            item_name='OptiPlex 7090 Desktop',
            category=self.category,
            brand=self.brand,
            department=self.dept,
            current_location=self.loc,
        )
        self.assertEqual(asset2.asset_code, 'CBA-IT-00002')

    def test_asset_code_stability_on_update(self):
        asset = Asset.objects.create(
            item_name='Latitude 5420 Laptop',
            category=self.category,
            brand=self.brand,
            department=self.dept,
            current_location=self.loc,
        )
        initial_code = asset.asset_code
        self.assertEqual(initial_code, 'CBA-IT-00001')

        # Update other fields
        asset.item_name = 'Updated Laptop Name'
        asset.acquisition_cost = Decimal('45000.00')
        asset.condition = Asset.Condition.GOOD
        asset.save()

        asset.refresh_from_db()
        self.assertEqual(asset.asset_code, initial_code)
        self.assertEqual(asset.item_name, 'Updated Laptop Name')

    def test_optional_serial_and_property_numbers(self):
        asset = Asset.objects.create(
            item_name='Conference Table',
            category=self.category,
            department=self.dept,
            serial_number='',
            property_number='',
        )
        self.assertEqual(asset.serial_number, '')
        self.assertEqual(asset.property_number, '')
        self.assertTrue(asset.asset_code.startswith('CBA-IT-'))

    def test_duplicate_property_number_validation(self):
        Asset.objects.create(
            item_name='First Device',
            category=self.category,
            department=self.dept,
            property_number='NORSU-PROP-999',
        )
        duplicate_asset = Asset(
            item_name='Second Device',
            category=self.category,
            department=self.dept,
            property_number='norsu-prop-999',  # case-insensitive check
        )
        with self.assertRaises(ValidationError):
            duplicate_asset.full_clean()

    def test_negative_acquisition_cost_validation(self):
        asset = Asset(
            item_name='Negative Cost Test',
            category=self.category,
            department=self.dept,
            acquisition_cost=Decimal('-500.00'),
        )
        with self.assertRaises(ValidationError):
            asset.full_clean()

    def test_status_and_condition_choices(self):
        asset = Asset.objects.create(
            item_name='Choice Test Asset',
            category=self.category,
            department=self.dept,
            status=Asset.Status.AVAILABLE,
            condition=Asset.Condition.NEW,
        )
        self.assertEqual(asset.status, 'AVAILABLE')
        self.assertEqual(asset.condition, 'NEW')
        self.assertEqual(asset.get_status_display(), 'Available')
        self.assertEqual(asset.get_condition_display(), 'New')


class AssetViewTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Users
        self.admin = User.objects.create_user(
            username='admin_inv',
            email='admin@cba.edu',
            password='Password123!',
            role=User.Role.ADMIN
        )
        self.dean = User.objects.create_user(
            username='dean_inv',
            email='dean@cba.edu',
            password='Password123!',
            role=User.Role.DEAN
        )
        self.chair_acct = User.objects.create_user(
            username='chair_acct',
            email='chair@cba.edu',
            password='Password123!',
            role=User.Role.DEPT_CHAIR
        )
        self.faculty = User.objects.create_user(
            username='faculty_user',
            email='faculty@cba.edu',
            password='Password123!',
            role=User.Role.FACULTY
        )

        # Organizations
        self.dept_acct = Department.objects.create(name='Accountancy', code='ACCT')
        self.dept_ba = Department.objects.create(name='Business Administration', code='BA')
        
        self.loc_acct = Location.objects.create(
            name='Accounting Office',
            building='CBA Annex',
            room_number='302',
            department=self.dept_acct
        )
        self.loc_ba = Location.objects.create(
            name='BA Dean Office',
            building='CBA Main',
            room_number='101',
            department=self.dept_ba
        )

        # Employee profile for chair
        self.chair_emp = Employee.objects.create(
            user=self.chair_acct,
            employee_id='EMP-CHAIR-01',
            first_name='Elena',
            last_name='Santos',
            department=self.dept_acct,
            location=self.loc_acct
        )

        # Categories & Brands
        self.cat_it = AssetCategory.objects.create(name='Information Technology', code='IT')
        self.cat_fn = AssetCategory.objects.create(name='Furniture', code='FN')
        self.brand_lenovo = Brand.objects.create(name='Lenovo')
        self.brand_dell = Brand.objects.create(name='Dell')

        # Assets
        self.asset_acct = Asset.objects.create(
            item_name='ThinkPad Laptop',
            category=self.cat_it,
            brand=self.brand_lenovo,
            model='L14',
            serial_number='SN-LENOVO-01',
            property_number='PROP-ACCT-001',
            department=self.dept_acct,
            current_location=self.loc_acct,
            condition=Asset.Condition.GOOD,
            status=Asset.Status.AVAILABLE,
            acquisition_cost=Decimal('50000.00'),
            created_by=self.admin
        )
        self.asset_ba = Asset.objects.create(
            item_name='Dell Workstation',
            category=self.cat_it,
            brand=self.brand_dell,
            model='OptiPlex',
            serial_number='SN-DELL-99',
            property_number='PROP-BA-002',
            department=self.dept_ba,
            current_location=self.loc_ba,
            condition=Asset.Condition.NEW,
            status=Asset.Status.AVAILABLE,
            acquisition_cost=Decimal('40000.00'),
            created_by=self.admin
        )

    def test_asset_list_access_permissions(self):
        # Admin can view all
        self.client.login(username='admin_inv', password='Password123!')
        res_admin = self.client.get(reverse('inventory:asset_list'))
        self.assertEqual(res_admin.status_code, 200)
        self.assertContains(res_admin, self.asset_acct.asset_code)
        self.assertContains(res_admin, self.asset_ba.asset_code)

        # Dean can view all
        self.client.login(username='dean_inv', password='Password123!')
        res_dean = self.client.get(reverse('inventory:asset_list'))
        self.assertEqual(res_dean.status_code, 200)
        self.assertContains(res_dean, self.asset_acct.asset_code)
        self.assertContains(res_dean, self.asset_ba.asset_code)

        # Chair can only view department assets
        self.client.login(username='chair_acct', password='Password123!')
        res_chair = self.client.get(reverse('inventory:asset_list'))
        self.assertEqual(res_chair.status_code, 200)
        self.assertContains(res_chair, self.asset_acct.asset_code)
        self.assertNotContains(res_chair, self.asset_ba.asset_code)

        # Faculty is restricted in Phase 2
        self.client.login(username='faculty_user', password='Password123!')
        res_fac = self.client.get(reverse('inventory:asset_list'))
        self.assertEqual(res_fac.status_code, 403)

    def test_asset_detail_access_and_scoping(self):
        # Admin can view both
        self.client.login(username='admin_inv', password='Password123!')
        res = self.client.get(reverse('inventory:asset_detail', kwargs={'asset_code': self.asset_acct.asset_code}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'ThinkPad Laptop')

        # Chair can view their department asset
        self.client.login(username='chair_acct', password='Password123!')
        res_chair_ok = self.client.get(reverse('inventory:asset_detail', kwargs={'asset_code': self.asset_acct.asset_code}))
        self.assertEqual(res_chair_ok.status_code, 200)

        # Chair is blocked from viewing other department asset
        res_chair_blocked = self.client.get(reverse('inventory:asset_detail', kwargs={'asset_code': self.asset_ba.asset_code}))
        self.assertEqual(res_chair_blocked.status_code, 403)

    def test_asset_create_workflow_and_audit(self):
        self.client.login(username='admin_inv', password='Password123!')
        create_url = reverse('inventory:asset_create')

        post_data = {
            'item_name': 'Epson Projector EB-X06',
            'category': self.cat_it.pk,
            'brand': self.brand_dell.pk,
            'model': 'EB-X06',
            'description': '3LCD Projector 3600 Lumens',
            'property_number': 'NORSU-NEW-2026',
            'serial_number': 'SN-PROJ-778',
            'department': self.dept_acct.pk,
            'current_location': self.loc_acct.pk,
            'acquisition_date': '2026-01-10',
            'acquisition_cost': '25000.00',
            'supplier': 'Columbia Technologies',
            'condition': Asset.Condition.NEW,
            'status': Asset.Status.AVAILABLE,
            'remarks': 'Classroom presentation equipment',
        }

        response = self.client.post(create_url, post_data)
        self.assertEqual(response.status_code, 302)

        created_asset = Asset.objects.get(property_number='NORSU-NEW-2026')
        self.assertTrue(created_asset.asset_code.startswith('CBA-IT-'))
        self.assertEqual(created_asset.created_by, self.admin)

        # Check Audit Log
        audit_log = AuditLog.objects.filter(
            model_name='Asset',
            action='ASSET_CREATED',
            object_id=str(created_asset.pk)
        ).first()
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.user, self.admin)
        self.assertIn('asset_code', audit_log.changes)

    def test_asset_update_workflow_and_audit(self):
        self.client.login(username='admin_inv', password='Password123!')
        edit_url = reverse('inventory:asset_edit', kwargs={'asset_code': self.asset_acct.asset_code})

        post_data = {
            'item_name': 'ThinkPad L14 Gen 3 (Upgraded 32GB)',
            'category': self.cat_it.pk,
            'brand': self.brand_lenovo.pk,
            'model': 'L14 Gen 3',
            'description': 'RAM upgraded to 32GB',
            'property_number': self.asset_acct.property_number,
            'serial_number': self.asset_acct.serial_number,
            'department': self.dept_acct.pk,
            'current_location': self.loc_acct.pk,
            'acquisition_cost': '55000.00',
            'condition': Asset.Condition.GOOD,
            'status': Asset.Status.AVAILABLE,
            'remarks': 'RAM expanded by IT services.',
        }

        response = self.client.post(edit_url, post_data)
        self.assertEqual(response.status_code, 302)

        self.asset_acct.refresh_from_db()
        self.assertEqual(self.asset_acct.item_name, 'ThinkPad L14 Gen 3 (Upgraded 32GB)')
        self.assertEqual(self.asset_acct.acquisition_cost, Decimal('55000.00'))

        # Check Audit Log for update
        audit_log = AuditLog.objects.filter(
            model_name='Asset',
            action='ASSET_UPDATED',
            object_id=str(self.asset_acct.pk)
        ).first()
        self.assertIsNotNone(audit_log)
        self.assertIn('item_name', audit_log.changes)

    def test_asset_delete_workflow_and_audit(self):
        self.client.login(username='admin_inv', password='Password123!')
        delete_url = reverse('inventory:asset_delete', kwargs={'asset_code': self.asset_ba.asset_code})

        # GET shows confirmation page
        get_res = self.client.get(delete_url)
        self.assertEqual(get_res.status_code, 200)
        self.assertContains(get_res, 'Confirm Permanent Deletion')

        # POST performs deletion
        post_res = self.client.post(delete_url)
        self.assertEqual(post_res.status_code, 302)
        self.assertFalse(Asset.objects.filter(asset_code=self.asset_ba.asset_code).exists())

        # Audit Log
        audit_log = AuditLog.objects.filter(
            model_name='Asset',
            action='ASSET_DELETED'
        ).first()
        self.assertIsNotNone(audit_log)
        self.assertEqual(audit_log.changes['asset_code'], self.asset_ba.asset_code)

    def test_asset_search_across_fields(self):
        self.client.login(username='admin_inv', password='Password123!')

        # Search by property number
        res_prop = self.client.get(reverse('inventory:asset_list') + '?q=PROP-ACCT-001')
        self.assertContains(res_prop, self.asset_acct.asset_code)
        self.assertNotContains(res_prop, self.asset_ba.asset_code)

        # Search by serial number
        res_sn = self.client.get(reverse('inventory:asset_list') + '?q=SN-DELL-99')
        self.assertContains(res_sn, self.asset_ba.asset_code)
        self.assertNotContains(res_sn, self.asset_acct.asset_code)

        # Search by model
        res_model = self.client.get(reverse('inventory:asset_list') + '?q=OptiPlex')
        self.assertContains(res_model, self.asset_ba.asset_code)
        self.assertNotContains(res_model, self.asset_acct.asset_code)

    def test_combined_filters(self):
        self.client.login(username='admin_inv', password='Password123!')

        # Filter by department
        url_filter = f"{reverse('inventory:asset_list')}?department={self.dept_acct.pk}&category={self.cat_it.pk}&condition=GOOD"
        res = self.client.get(url_filter)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, self.asset_acct.asset_code)
        self.assertNotContains(res, self.asset_ba.asset_code)

    def test_asset_list_htmx_partial_response(self):
        self.client.login(username='admin_inv', password='Password123!')
        
        # Standard GET returns full page
        res_full = self.client.get(reverse('inventory:asset_list'))
        self.assertEqual(res_full.status_code, 200)
        self.assertTemplateUsed(res_full, 'inventory/asset_list.html')
        self.assertTemplateUsed(res_full, 'inventory/partials/_asset_results.html')
        self.assertContains(res_full, 'id="assetFilterForm"')
        self.assertContains(res_full, 'id="asset-results-container"')

        # HTMX GET request returns ONLY the partial template
        res_htmx = self.client.get(
            reverse('inventory:asset_list'),
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(res_htmx.status_code, 200)
        self.assertTemplateUsed(res_htmx, 'inventory/partials/_asset_results.html')
        self.assertTemplateNotUsed(res_htmx, 'inventory/asset_list.html')
        self.assertNotContains(res_htmx, 'id="assetFilterForm"')
        self.assertContains(res_htmx, self.asset_acct.asset_code)
        self.assertContains(res_htmx, self.asset_ba.asset_code)

    def test_asset_list_htmx_history_restore_returns_full_page(self):
        self.client.login(username='admin_inv', password='Password123!')
        res_restore = self.client.get(
            reverse('inventory:asset_list'),
            HTTP_HX_REQUEST='true',
            HTTP_HX_HISTORY_RESTORE_REQUEST='true'
        )
        self.assertEqual(res_restore.status_code, 200)
        self.assertTemplateUsed(res_restore, 'inventory/asset_list.html')
        self.assertContains(res_restore, 'id="assetFilterForm"')

    def test_asset_list_htmx_search_filtering(self):
        self.client.login(username='admin_inv', password='Password123!')

        # Live search for ThinkPad
        res = self.client.get(
            reverse('inventory:asset_list') + '?q=ThinkPad',
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, self.asset_acct.asset_code)
        self.assertNotContains(res, self.asset_ba.asset_code)

    def test_asset_list_htmx_dropdown_filtering(self):
        self.client.login(username='admin_inv', password='Password123!')

        # Filter by department BA
        res = self.client.get(
            f"{reverse('inventory:asset_list')}?department={self.dept_ba.pk}",
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, self.asset_ba.asset_code)
        self.assertNotContains(res, self.asset_acct.asset_code)

    def test_asset_list_htmx_empty_state_without_table(self):
        self.client.login(username='admin_inv', password='Password123!')

        # Search for non-existent asset
        res = self.client.get(
            reverse('inventory:asset_list') + '?q=NON_EXISTENT_QUERY_XYZ',
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'No Assets Found')
        self.assertContains(res, 'Clear Filters')
        self.assertNotContains(res, '<table')
        self.assertNotContains(res, '<thead')

    def test_asset_list_htmx_scoping(self):
        # Dept Chair scoping preserved under HTMX
        self.client.login(username='chair_acct', password='Password123!')
        res_chair = self.client.get(
            reverse('inventory:asset_list'),
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(res_chair.status_code, 200)
        self.assertContains(res_chair, self.asset_acct.asset_code)
        self.assertNotContains(res_chair, self.asset_ba.asset_code)

        # Faculty 403 preserved under HTMX
        self.client.login(username='faculty_user', password='Password123!')
        res_fac = self.client.get(
            reverse('inventory:asset_list'),
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(res_fac.status_code, 403)

    def test_asset_list_status_tabs_count_ignores_selected_status(self):
        self.asset_ba.status = Asset.Status.DAMAGED
        self.asset_ba.save()
        self.client.login(username='admin_inv', password='Password123!')
        res = self.client.get(reverse('inventory:asset_list'), {'status': Asset.Status.DAMAGED})
        tabs = {tab['label']: tab for tab in res.context['status_tabs']}
        self.assertEqual(tabs['All']['count'], 2)
        self.assertEqual(tabs['Available']['count'], 1)
        self.assertEqual(tabs['Damaged']['count'], 1)
        self.assertTrue(tabs['Damaged']['active'])
        self.assertEqual(list(res.context['assets']), [self.asset_ba])

    def test_asset_list_keeps_filter_values_and_lists_active_filters(self):
        self.client.login(username='admin_inv', password='Password123!')
        res = self.client.get(reverse('inventory:asset_list'), {'q': 'laptop', 'department': self.dept_acct.pk})
        self.assertEqual(res.context['current_q'], 'laptop')
        self.assertEqual(res.context['current_department'], str(self.dept_acct.pk))
        self.assertEqual([f['field'] for f in res.context['active_filters']], ['q', 'department'])
        self.assertContains(res, 'value="laptop"')

    def test_asset_list_search_covers_location_and_current_holder(self):
        AssetAssignment.objects.create(
            asset=self.asset_acct, employee=self.chair_emp, assigned_date=date(2026, 1, 5), assigned_by=self.admin
        )
        self.client.login(username='admin_inv', password='Password123!')
        by_room = self.client.get(reverse('inventory:asset_list'), {'q': 'BA Dean'})
        self.assertEqual(list(by_room.context['assets']), [self.asset_ba])
        by_holder = self.client.get(reverse('inventory:asset_list'), {'q': 'Elena Santos'})
        self.assertEqual(list(by_holder.context['assets']), [self.asset_acct])
        self.assertContains(by_holder, 'Elena Santos')

    def test_asset_list_sort_puts_damaged_first(self):
        self.asset_acct.status = Asset.Status.DAMAGED
        self.asset_acct.save()
        self.client.login(username='admin_inv', password='Password123!')
        res = self.client.get(reverse('inventory:asset_list'), {'sort': 'need'})
        self.assertEqual(list(res.context['assets']), [self.asset_acct, self.asset_ba])

    def test_asset_list_htmx_pagination(self):
        self.client.login(username='admin_inv', password='Password123!')
        # Bulk create 20 assets to trigger pagination (paginate_by is 15)
        Asset.objects.bulk_create([
            Asset(
                item_name=f'Bulk Asset {i}',
                asset_code=f'CBA-IT-99{i:03d}',
                category=self.cat_it,
                brand=self.brand_lenovo,
                department=self.dept_acct,
                current_location=self.loc_acct,
                acquisition_cost=Decimal('1000.00'),
                condition=Asset.Condition.GOOD,
                status=Asset.Status.AVAILABLE,
                created_by=self.admin
            )
            for i in range(20)
        ])

        # Page 1
        res_p1 = self.client.get(
            reverse('inventory:asset_list') + '?page=1',
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(res_p1.status_code, 200)
        self.assertContains(res_p1, 'Showing 1–15 of 22 assets')
        self.assertContains(res_p1, 'hx-target="#asset-results-container"')
        self.assertContains(res_p1, 'page=2')

        # Page 2
        res_p2 = self.client.get(
            reverse('inventory:asset_list') + '?page=2',
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(res_p2.status_code, 200)
        self.assertContains(res_p2, 'Showing 16–22 of 22 assets')


class CategoryAndBrandViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='admin_cat_brand',
            password='Password123!',
            role=User.Role.ADMIN
        )
        self.category = AssetCategory.objects.create(name='Office Equipment', code='OE')
        self.brand = Brand.objects.create(name='Samsung')

    def test_category_list_and_create(self):
        self.client.login(username='admin_cat_brand', password='Password123!')

        response = self.client.get(reverse('inventory:category_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Office Equipment')

        create_url = reverse('inventory:category_create')
        response = self.client.post(create_url, {
            'name': 'Appliances',
            'code': 'AP',
            'description': 'Air conditioners, refrigerators',
            'is_active': True,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(AssetCategory.objects.filter(code='AP').exists())

    def test_brand_list_and_create(self):
        self.client.login(username='admin_cat_brand', password='Password123!')

        response = self.client.get(reverse('inventory:brand_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Samsung')

        create_url = reverse('inventory:brand_create')
        response = self.client.post(create_url, {
            'name': 'HP Inc.',
            'is_active': True,
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Brand.objects.filter(name='HP Inc.').exists())

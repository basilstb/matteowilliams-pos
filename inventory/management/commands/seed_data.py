from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta, date
from decimal import Decimal
from inventory.models import (
    SystemSettings, Branch, Category, Product, BranchStock, Customer,
    Sale, SaleItem, PaymentSplit, DebtRepayment, AuditLog
)


class Command(BaseCommand):
    help = "Seeds initial branches, electronics inventory, and sample transactions for Matteo Williams"

    def handle(self, *args, **options):
        self.stdout.write("Initializing Matteo Williams Electronics Onitsha Database...")

        # 1. System Settings
        settings = SystemSettings.get_settings()
        settings.business_name = "Matteo Williams Electronics"
        settings.business_tagline = "Premier Electronics, Sound & Solar Power Hub - Onitsha"
        settings.business_phone = "+234 803 765 4321"
        settings.business_address = "Main Market / Emeka Offor / Iweka Road, Onitsha, Anambra State"
        settings.general_password = "Matteo2025"
        settings.owner_username = "owner"
        settings.owner_pin = "0000"
        settings.owner_password = "Owner@Matteo2025"
        settings.save()
        self.stdout.write(self.style.SUCCESS("[OK] System settings saved (Gatekeeper password: Matteo2025, Owner Master PIN: 0000)"))

        # 2. Branches
        branches_data = [
            {
                'name': 'Main Market Hub',
                'code': 'MW-MM01',
                'location': 'Line 4, Sokoto Road, Main Market, Onitsha',
                'phone': '+234 803 111 2233',
                'cashier_pin': '1111',
                'manager_pin': '9911',
            },
            {
                'name': 'Emeka Offor Plaza Branch',
                'code': 'MW-EOP2',
                'location': 'Shop B-12, Emeka Offor Electronics Plaza, Onitsha',
                'phone': '+234 802 222 3344',
                'cashier_pin': '2222',
                'manager_pin': '9922',
            },
            {
                'name': 'Iweka Road Sound & Solar',
                'code': 'MW-IWK3',
                'location': 'No. 45 Iweka Road, Near Upper Iweka Flyover, Onitsha',
                'phone': '+234 814 333 4455',
                'cashier_pin': '3333',
                'manager_pin': '9933',
            },
        ]

        created_branches = []
        for b_data in branches_data:
            branch, _ = Branch.objects.update_or_create(
                code=b_data['code'],
                defaults=b_data
            )
            created_branches.append(branch)
        self.stdout.write(self.style.SUCCESS(f"[OK] {len(created_branches)} Onitsha branches configured with distinct PINs"))

        # 3. Categories
        categories_data = [
            ('Smart TVs & Displays', 'tv', 'High Definition, 4K, 8K Smart and OLED displays'),
            ('Sound Systems & Audio', 'speaker', 'Hi-Fi systems, home theaters, soundbars, DJ systems'),
            ('Solar Inverters & Batteries', 'zap', 'Pure sine wave inverters, tubular and lithium batteries'),
            ('Refrigeration & Cooling', 'snowflake', 'Deep freezers, double-door refrigerators, air conditioners'),
            ('Voltage Stabilizers & UPS', 'shield-check', 'Heavy duty servo stabilizers and power protection'),
            ('Phones & Accessories', 'smartphone', 'Smartphones, fast chargers, power banks'),
            ('Cables & Installation', 'cable', 'Pure copper cables, solar breakers, TV brackets'),
        ]

        category_objs = {}
        for name, icon, desc in categories_data:
            cat, _ = Category.objects.get_or_create(
                name=name,
                defaults={'icon_name': icon, 'description': desc}
            )
            category_objs[name] = cat

        # 4. Products
        products_data = [
            # TVs
            {
                'category': category_objs['Smart TVs & Displays'],
                'name': 'Samsung 55" Crystal UHD 4K Smart TV (CU7000)',
                'brand': 'Samsung',
                'sku': 'SAM-55-CU7',
                'cost_price': Decimal('440000.00'),
                'selling_price': Decimal('520000.00'),
                'min_selling_price': Decimal('490000.00'),
                'unit': 'pcs',
                'warranty_info': '2 Years Official Samsung Warranty',
                'stocks': [12, 8, 6],
            },
            {
                'category': category_objs['Smart TVs & Displays'],
                'name': 'LG 65" OLED evo 4K Smart TV (C3 Series)',
                'brand': 'LG',
                'sku': 'LG-65-OLED',
                'cost_price': Decimal('1150000.00'),
                'selling_price': Decimal('1350000.00'),
                'min_selling_price': Decimal('1280000.00'),
                'unit': 'pcs',
                'warranty_info': '2 Years LG Warranty',
                'stocks': [4, 5, 2],
            },
            {
                'category': category_objs['Smart TVs & Displays'],
                'name': 'Hisense 43" Smart Full HD LED Frameless TV',
                'brand': 'Hisense',
                'sku': 'HIS-43-FHD',
                'cost_price': Decimal('2050000.00') / 10, # 205,000
                'selling_price': Decimal('245000.00'),
                'min_selling_price': Decimal('230000.00'),
                'unit': 'pcs',
                'warranty_info': '1 Year Warranty',
                'stocks': [15, 18, 10],
            },
            # Sound
            {
                'category': category_objs['Sound Systems & Audio'],
                'name': 'LG XBOOM CL98 3500W High Power Audio System',
                'brand': 'LG',
                'sku': 'LG-XB-CL98',
                'cost_price': Decimal('410000.00'),
                'selling_price': Decimal('485000.00'),
                'min_selling_price': Decimal('460000.00'),
                'unit': 'set',
                'warranty_info': '1 Year Official Warranty',
                'stocks': [6, 4, 9],
            },
            {
                'category': category_objs['Sound Systems & Audio'],
                'name': 'Sony MHC-V43D High-Power Audio System Bluetooth',
                'brand': 'Sony',
                'sku': 'SNY-MHC-V43',
                'cost_price': Decimal('325000.00'),
                'selling_price': Decimal('390000.00'),
                'min_selling_price': Decimal('370000.00'),
                'unit': 'set',
                'warranty_info': '1 Year Sony Warranty',
                'stocks': [8, 5, 11],
            },
            # Solar
            {
                'category': category_objs['Solar Inverters & Batteries'],
                'name': 'Felicity Solar 5KVA 48V Pure Sine Wave Inverter',
                'brand': 'Felicity Solar',
                'sku': 'FEL-5KVA-48',
                'cost_price': Decimal('580000.00'),
                'selling_price': Decimal('680000.00'),
                'min_selling_price': Decimal('640000.00'),
                'unit': 'pcs',
                'warranty_info': '2 Years Factory Warranty',
                'stocks': [5, 4, 14],
            },
            {
                'category': category_objs['Solar Inverters & Batteries'],
                'name': 'Luminous 220Ah 12V Tall Tubular Solar Battery',
                'brand': 'Luminous',
                'sku': 'LUM-220AH-TT',
                'cost_price': Decimal('265000.00'),
                'selling_price': Decimal('310000.00'),
                'min_selling_price': Decimal('295000.00'),
                'unit': 'pcs',
                'warranty_info': '18 Months Warranty',
                'stocks': [20, 15, 25],
            },
            # Cooling
            {
                'category': category_objs['Refrigeration & Cooling'],
                'name': 'Nexus 250L Inverter Chest Deep Freezer (Silver)',
                'brand': 'Nexus',
                'sku': 'NEX-250L-DF',
                'cost_price': Decimal('290000.00'),
                'selling_price': Decimal('340000.00'),
                'min_selling_price': Decimal('320000.00'),
                'unit': 'pcs',
                'warranty_info': '3 Years Compressor Warranty',
                'stocks': [7, 6, 4],
            },
            # Stabilizers
            {
                'category': category_objs['Voltage Stabilizers & UPS'],
                'name': 'Century 5000VA Automatic Voltage Stabilizer (Servo)',
                'brand': 'Century',
                'sku': 'CEN-5000-AVR',
                'cost_price': Decimal('78000.00'),
                'selling_price': Decimal('95000.00'),
                'min_selling_price': Decimal('88000.00'),
                'unit': 'pcs',
                'warranty_info': '1 Year Warranty',
                'stocks': [25, 30, 20],
            },
            # Phones
            {
                'category': category_objs['Phones & Accessories'],
                'name': 'Samsung Galaxy S24 Ultra 256GB Dual SIM',
                'brand': 'Samsung',
                'sku': 'SAM-S24U-256',
                'cost_price': Decimal('1250000.00'),
                'selling_price': Decimal('1420000.00'),
                'min_selling_price': Decimal('1360000.00'),
                'unit': 'pcs',
                'warranty_info': '24 Months Official Warranty',
                'stocks': [5, 12, 3],
            },
            # Cables
            {
                'category': category_objs['Cables & Installation'],
                'name': 'Heavy Duty 16mm Pure Copper Solar Cable (100m Roll)',
                'brand': 'Coleman',
                'sku': 'COL-16MM-100M',
                'cost_price': Decimal('102000.00'),
                'selling_price': Decimal('125000.00'),
                'min_selling_price': Decimal('115000.00'),
                'unit': 'roll',
                'warranty_info': '100% Pure Copper Guarantee',
                'stocks': [15, 20, 18],
            },
        ]

        created_products = []
        for p_data in products_data:
            stocks = p_data.pop('stocks')
            product, _ = Product.objects.update_or_create(
                sku=p_data['sku'],
                defaults=p_data
            )
            created_products.append(product)
            # Create stocks per branch
            for idx, branch in enumerate(created_branches):
                qty = stocks[idx] if idx < len(stocks) else 5
                BranchStock.objects.update_or_create(
                    branch=branch,
                    product=product,
                    defaults={'quantity': qty, 'reorder_level': 4}
                )

        self.stdout.write(self.style.SUCCESS(f"[OK] {len(created_products)} Electronics products stocked across all branches"))

        # 5. Customers & Debtor Records
        customers_data = [
            {
                'name': 'Chief Emeka Okonkwo (Onyeka Electronics)',
                'phone': '08034567890',
                'address': 'Line 2 Shop 18, Main Market, Onitsha',
                'business_name': 'Onyeka Electronics & Sound',
                'guarantor_name': 'Chief Innocent Maduka',
                'guarantor_phone': '08031119988',
            },
            {
                'name': 'Engr. Chinedu Eze (Solar Pro Tech)',
                'phone': '08023456789',
                'address': 'No. 12 New Market Road, Onitsha',
                'business_name': 'Chinedu Solar Installations',
                'guarantor_name': 'Pastor Jude Obi',
                'guarantor_phone': '08032228877',
            },
            {
                'name': 'Madam Amaka Obi (VIP Boutique)',
                'phone': '08145678901',
                'address': 'Emeka Offor Plaza Block C-04, Onitsha',
                'business_name': 'VIP Fashion House',
                'guarantor_name': 'Mr. Anthony Obi',
                'guarantor_phone': '08039991122',
            },
            {
                'name': 'Brother Kenechukwu Nnamdi',
                'phone': '08061239874',
                'address': 'Iweka Road Motor Park Area, Onitsha',
                'business_name': 'Kene Sound Rental',
                'guarantor_name': 'Alhaji Musa Garba',
                'guarantor_phone': '08024445566',
            },
        ]

        cust_objs = []
        for c_data in customers_data:
            cust, _ = Customer.objects.update_or_create(
                phone=c_data['phone'],
                defaults=c_data
            )
            cust_objs.append(cust)

        # 6. Sample Sales: One Paid, One Split Payment with Debt, One Full Debt
        now = timezone.now()

        # Sale 1: Paid in Full with Split Payment (Cash + Transfer) at Main Market
        s1, s1_created = Sale.objects.get_or_create(
            invoice_number='MW-MM-2026-0001',
            defaults={
                'branch': created_branches[0],
                'cashier_name': 'Chuka (Cashier 1)',
                'customer': cust_objs[0],
                'customer_name_snapshot': cust_objs[0].name,
                'customer_phone_snapshot': cust_objs[0].phone,
                'subtotal': Decimal('520000.00'),
                'total_amount': Decimal('520000.00'),
                'amount_paid': Decimal('520000.00'),
                'balance_owed': Decimal('0.00'),
                'payment_status': 'PAID_FULL',
                'created_at': now - timedelta(days=2, hours=4),
            }
        )
        if s1_created:
            prod_tv = created_products[0]
            SaleItem.objects.create(sale=s1, product=prod_tv, unit_price=Decimal('520000.00'), quantity=1, subtotal=Decimal('520000.00'))
            PaymentSplit.objects.create(sale=s1, method='CASH', amount=Decimal('220000.00'), reference_note='Cash at counter', created_at=s1.created_at)
            PaymentSplit.objects.create(sale=s1, method='TRANSFER', amount=Decimal('300000.00'), reference_note='Access Bank transfer ref #ACC892182', created_at=s1.created_at)

        # Sale 2: Split Payment with Partial Debt at Emeka Offor Plaza
        # Total: ₦875,000 (LG Sound System ₦485k + Sony Sound ₦390k).
        # Customer pays: ₦275k Transfer, ₦200k Cash, owes ₦400k debt. Later repaid ₦150k!
        s2, s2_created = Sale.objects.get_or_create(
            invoice_number='MW-EO-2026-0002',
            defaults={
                'branch': created_branches[1],
                'cashier_name': 'Ngozi (Cashier 2)',
                'customer': cust_objs[1],
                'customer_name_snapshot': cust_objs[1].name,
                'customer_phone_snapshot': cust_objs[1].phone,
                'subtotal': Decimal('875000.00'),
                'total_amount': Decimal('875000.00'),
                'amount_paid': Decimal('625000.00'),  # initially 475k + 150k repaid
                'balance_owed': Decimal('250000.00'),
                'payment_status': 'PARTIAL_DEBT',
                'debt_due_date': (now + timedelta(days=10)).date(),
                'notes': 'Deposit paid on sound equipment. Balance promised end of month.',
                'created_at': now - timedelta(days=4, hours=2),
            }
        )
        if s2_created:
            prod_lg_sound = created_products[3]
            prod_sony = created_products[4]
            SaleItem.objects.create(sale=s2, product=prod_lg_sound, unit_price=Decimal('485000.00'), quantity=1, subtotal=Decimal('485000.00'))
            SaleItem.objects.create(sale=s2, product=prod_sony, unit_price=Decimal('390000.00'), quantity=1, subtotal=Decimal('390000.00'))
            PaymentSplit.objects.create(sale=s2, method='TRANSFER', amount=Decimal('275000.00'), reference_note='Moniepoint transfer ref #MP98412', created_at=s2.created_at)
            PaymentSplit.objects.create(sale=s2, method='CASH', amount=Decimal('200000.00'), reference_note='Cash advance', created_at=s2.created_at)
            PaymentSplit.objects.create(sale=s2, method='DEBT', amount=Decimal('400000.00'), reference_note='Outstanding credit agreement', created_at=s2.created_at)
            
            # Debt repayment event: customer later brought ₦150k!
            DebtRepayment.objects.create(
                receipt_number='DRP-2026-001',
                sale=s2,
                customer=cust_objs[1],
                amount_paid=Decimal('150000.00'),
                payment_method='TRANSFER',
                balance_before=Decimal('400000.00'),
                balance_after=Decimal('250000.00'),
                received_by='Emeka (Manager)',
                received_by_role='Manager',
                reference_note='First debt installment paid via Opay transfer ref #OPY77612',
                created_at=now - timedelta(days=1, hours=3)
            )

        # Sale 3: 100% Credit / Full Debt at Iweka Road
        # Total: ₦310,000 (Luminous Battery). Customer paid ₦0, owes ₦310,000.
        s3, s3_created = Sale.objects.get_or_create(
            invoice_number='MW-IW-2026-0003',
            defaults={
                'branch': created_branches[2],
                'cashier_name': 'Obinna (Cashier 3)',
                'customer': cust_objs[2],
                'customer_name_snapshot': cust_objs[2].name,
                'customer_phone_snapshot': cust_objs[2].phone,
                'subtotal': Decimal('310000.00'),
                'total_amount': Decimal('310000.00'),
                'amount_paid': Decimal('0.00'),
                'balance_owed': Decimal('310000.00'),
                'payment_status': 'FULL_DEBT',
                'debt_due_date': (now + timedelta(days=5)).date(),
                'notes': '100% Credit for VIP boutique inverter backup. Manager approved.',
                'approved_by': 'Ifeanyi (Iweka Manager)',
                'created_at': now - timedelta(days=1, hours=6),
            }
        )
        if s3_created:
            prod_batt = created_products[6]
            SaleItem.objects.create(sale=s3, product=prod_batt, unit_price=Decimal('310000.00'), quantity=1, subtotal=Decimal('310000.00'))
            PaymentSplit.objects.create(sale=s3, method='DEBT', amount=Decimal('310000.00'), reference_note='100% credit approved by manager', created_at=s3.created_at)

        # 7. Audit Log Sample Entries
        AuditLog.objects.create(
            branch=created_branches[0],
            user_role='GATEWAY',
            actor_name='Terminal Cashier',
            action_type='GATEWAY_UNLOCKED',
            details='General gatekeeper password successfully entered',
            ip_address='127.0.0.1',
            created_at=now - timedelta(days=2, hours=5)
        )
        AuditLog.objects.create(
            branch=created_branches[1],
            user_role='MANAGER',
            actor_name='Emeka (Manager)',
            action_type='DEBT_REPAID',
            details='Recorded ₦150,000 debt repayment for invoice MW-EO-2026-0002. Remaining balance: ₦250,000',
            ip_address='127.0.0.1',
            created_at=now - timedelta(days=1, hours=3)
        )

        self.stdout.write(self.style.SUCCESS("[OK] Seed transactions, split payments, debts, and repayments successfully created!"))

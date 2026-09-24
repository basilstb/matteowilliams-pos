from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.http import JsonResponse
from decimal import Decimal
import json

from .models import (
    Branch, Category, Product, BranchStock, Customer,
    Sale, SaleItem, PaymentSplit, AuditLog
)
from .decorators import require_general_gateway, require_roles, require_branch
from .views_auth import get_client_ip


@require_general_gateway
@require_roles('CASHIER', 'MANAGER', 'OWNER')
@require_branch
def pos_terminal_view(request):
    """Modern Fintech POS Terminal with high-visibility product grid, split payments, and customer management."""
    branch_id = request.session.get('branch_id')
    user_role = request.session.get('user_role')
    
    # If Owner doesn't have a branch set in session, pick the first active branch or from query param
    if user_role == 'OWNER' and not branch_id:
        selected_branch_id = request.GET.get('branch')
        if selected_branch_id:
            branch = get_object_or_404(Branch, id=selected_branch_id)
        else:
            branch = Branch.objects.filter(is_active=True).first()
    else:
        branch = get_object_or_404(Branch, id=branch_id)
        
    categories = Category.objects.all().order_by('name')
    selected_cat = request.GET.get('category', 'all')
    search_q = request.GET.get('q', '').strip()
    
    # Fetch branch stocks
    stocks_qs = BranchStock.objects.filter(branch=branch, product__is_active=True).select_related('product', 'product__category')
    
    if selected_cat != 'all' and selected_cat.isdigit():
        stocks_qs = stocks_qs.filter(product__category_id=int(selected_cat))
        
    if search_q:
        stocks_qs = stocks_qs.filter(
            product__name__icontains=search_q
        ) | stocks_qs.filter(
            product__sku__icontains=search_q
        ) | stocks_qs.filter(
            product__brand__icontains=search_q
        )
        
    customers = Customer.objects.all().order_by('name')
    
    # Recent branch sales for quick reference
    recent_sales = Sale.objects.filter(branch=branch).order_by('-created_at')[:6]

    return render(request, 'inventory/pos/terminal.html', {
        'terminal_branch': branch,
        'stocks': stocks_qs,
        'categories': categories,
        'selected_cat': selected_cat,
        'search_q': search_q,
        'customers': customers,
        'recent_sales': recent_sales,
        'user_role': user_role,
        'now': timezone.now(),
    })


@require_general_gateway
@require_roles('CASHIER', 'MANAGER', 'OWNER')
@require_branch
def process_sale_view(request):
    """Handles Split Payments, Debt generation, inventory stock decrement, and boundaries."""
    if request.method != 'POST':
        return redirect('inventory:pos_terminal')
        
    branch_id = request.session.get('branch_id')
    user_role = request.session.get('user_role')
    actor_name = request.session.get('actor_name', 'Cashier')
    
    if user_role == 'OWNER' and not branch_id:
        branch = Branch.objects.filter(is_active=True).first()
    else:
        branch = get_object_or_404(Branch, id=branch_id)

    try:
        # Parse Cart JSON
        cart_data_raw = request.POST.get('cart_json', '[]')
        cart_items = json.loads(cart_data_raw)
        
        if not cart_items:
            messages.error(request, "Cannot complete sale: Cart is empty. Please select products.")
            return redirect('inventory:pos_terminal')
            
        # Parse Payment Split Inputs
        cash_val = Decimal(request.POST.get('split_cash', '0.00') or '0.00')
        transfer_val = Decimal(request.POST.get('split_transfer', '0.00') or '0.00')
        pos_val = Decimal(request.POST.get('split_pos', '0.00') or '0.00')
        debt_val = Decimal(request.POST.get('split_debt', '0.00') or '0.00')
        
        transfer_ref = request.POST.get('transfer_ref', '').strip()
        pos_ref = request.POST.get('pos_ref', '').strip()
        debt_due_date_str = request.POST.get('debt_due_date', '').strip()
        sale_notes = request.POST.get('sale_notes', '').strip()
        discount_value = Decimal(request.POST.get('discount_value', '0') or '0')
        discount_mode = request.POST.get('discount_mode', 'flat').strip()
        
        customer_id = request.POST.get('customer_id', '').strip()
        cust_name_manual = request.POST.get('customer_name_manual', '').strip()
        cust_phone_manual = request.POST.get('customer_phone_manual', '').strip()
        cust_address_manual = request.POST.get('customer_address_manual', '').strip()

        # Customer Resolution
        customer = None
        if customer_id and customer_id != 'new' and customer_id != 'walkin':
            customer = Customer.objects.filter(id=customer_id).first()
            if customer:
                cust_name_manual = customer.name
                cust_phone_manual = customer.phone
        elif cust_phone_manual:
            customer, _ = Customer.objects.get_or_create(
                phone=cust_phone_manual,
                defaults={
                    'name': cust_name_manual or f"Customer {cust_phone_manual}",
                    'address': cust_address_manual
                }
            )

        # Cashier Boundary: Debt requires customer details!
        if debt_val > Decimal('0.00'):
            if not cust_name_manual or not cust_phone_manual:
                messages.error(request, "DEBT RESTRICTION: A customer name and active phone number are required for any credit or split debt sale.")
                return redirect('inventory:pos_terminal')

        # Cashier Boundary: 100% Credit or large debt requires Manager PIN if user is Cashier
        total_payment_given = cash_val + transfer_val + pos_val
        is_full_credit = (total_payment_given == Decimal('0.00') and debt_val > Decimal('0.00'))
        is_large_debt = (debt_val > Decimal('200000.00'))
        
        manager_approved = True
        approved_by = actor_name
        
        if (is_full_credit or is_large_debt) and user_role == 'CASHIER':
            manager_override_pin = request.POST.get('manager_override_pin', '').strip()
            if manager_override_pin != branch.manager_pin:
                messages.error(request, f"PERMISSION BOUNDARY: Debt sales of 100% credit or exceeding ₦200,000 require Branch Manager approval PIN. Invalid or missing Manager PIN.")
                return redirect('inventory:pos_terminal')
            approved_by = f"Manager Override ({branch.name})"

        # Execute Transaction Atomically
        with transaction.atomic():
            # Calculate bill total and check stock
            total_bill = Decimal('0.00')
            items_to_create = []
            stocks_to_update = []
            
            for item in cart_items:
                product_id = item.get('product_id')
                qty = int(item.get('quantity', 1))
                custom_price = Decimal(str(item.get('price', 0)))
                
                product = Product.objects.get(id=product_id)
                branch_stock = BranchStock.objects.select_for_update().get(branch=branch, product=product)
                
                # Check stock availability
                if branch_stock.quantity < qty:
                    raise ValueError(f"Insufficient stock for {product.name}. Available: {branch_stock.quantity}, Requested: {qty}")
                    
                # Cashier boundary: floor price check
                if custom_price < product.min_selling_price and user_role == 'CASHIER':
                    raise ValueError(f"PRICE BOUNDARY: {product.name} cannot be sold below floor price of ₦{product.min_selling_price:,.2f} without manager override.")
                    
                line_subtotal = custom_price * qty
                total_bill += line_subtotal
                
                # Decrement stock
                branch_stock.quantity -= qty
                stocks_to_update.append(branch_stock)
                
                items_to_create.append({
                    'product': product,
                    'unit_price': custom_price,
                    'quantity': qty,
                    'subtotal': line_subtotal
                })

            # Validate Split Payment matching total bill
            # Apply discount
            if discount_mode == 'pct':
                discount_pct = min(discount_value, Decimal('100'))
                discount_amount = (total_bill * discount_pct / Decimal('100')).quantize(Decimal('0.01'))
            else:
                discount_amount = min(discount_value, total_bill)
            net_total = max(Decimal('0.00'), total_bill - discount_amount)

            total_splits = cash_val + transfer_val + pos_val + debt_val
            if abs(total_splits - net_total) > Decimal('0.01'):
                raise ValueError(f"PAYMENT SPLIT MISMATCH: Net Total after discount is ₦{net_total:,.2f}, but split sum is ₦{total_splits:,.2f}. Please balance the figures.")

            # Generate Invoice Number: MW-{BRANCH_CODE}-{YYYYMMDD}-{ID}
            date_str = timezone.now().strftime('%Y%m%d')
            today_count = Sale.objects.filter(branch=branch, created_at__date=timezone.now().date()).count() + 1
            invoice_num = f"MW-{branch.code}-{date_str}-{today_count:04d}"

            # Payment Status
            if debt_val <= Decimal('0.00'):
                payment_status = 'PAID_FULL'
            elif total_payment_given > Decimal('0.00'):
                payment_status = 'PARTIAL_DEBT'
            else:
                payment_status = 'FULL_DEBT'

            due_date = None
            if debt_due_date_str:
                due_date = timezone.datetime.strptime(debt_due_date_str, '%Y-%m-%d').date()

            # Create Sale Record
            sale = Sale.objects.create(
                invoice_number=invoice_num,
                branch=branch,
                cashier_name=actor_name,
                customer=customer,
                customer_name_snapshot=cust_name_manual,
                customer_phone_snapshot=cust_phone_manual,
                subtotal=total_bill,
                discount=discount_amount,
                total_amount=net_total,
                amount_paid=total_payment_given,
                balance_owed=debt_val,
                payment_status=payment_status,
                debt_due_date=due_date,
                is_manager_approved=manager_approved,
                approved_by=approved_by,
                notes=sale_notes,
                created_at=timezone.now()
            )

            # Create Sale Items & Save Stock
            for stock_obj in stocks_to_update:
                stock_obj.save()

            for it in items_to_create:
                SaleItem.objects.create(
                    sale=sale,
                    product=it['product'],
                    unit_price=it['unit_price'],
                    quantity=it['quantity'],
                    subtotal=it['subtotal']
                )

            # Create Split Records
            if cash_val > Decimal('0.00'):
                PaymentSplit.objects.create(
                    sale=sale,
                    method='CASH',
                    amount=cash_val,
                    reference_note='Cash Received at Counter',
                    created_at=timezone.now()
                )

            if transfer_val > Decimal('0.00'):
                PaymentSplit.objects.create(
                    sale=sale,
                    method='TRANSFER',
                    amount=transfer_val,
                    reference_note=transfer_ref or 'Bank Transfer Verified',
                    created_at=timezone.now()
                )

            if pos_val > Decimal('0.00'):
                PaymentSplit.objects.create(
                    sale=sale,
                    method='POS',
                    amount=pos_val,
                    reference_note=pos_ref or 'POS Terminal Slip Verified',
                    created_at=timezone.now()
                )

            if debt_val > Decimal('0.00'):
                PaymentSplit.objects.create(
                    sale=sale,
                    method='DEBT',
                    amount=debt_val,
                    reference_note=f"Outstanding Debt. Due: {due_date or 'On Agreement'}",
                    created_at=timezone.now()
                )

            # Audit Log
            AuditLog.objects.create(
                branch=branch,
                user_role=user_role,
                actor_name=actor_name,
                action_type='SALE_CREATED',
                details=f"Sale {sale.invoice_number} created. Subtotal: ₦{total_bill:,.2f} | Discount: ₦{discount_amount:,.2f} | Total: ₦{net_total:,.2f} | Paid: ₦{total_payment_given:,.2f} | Debt: ₦{debt_val:,.2f}",
                ip_address=get_client_ip(request),
                created_at=timezone.now()
            )

        messages.success(request, f"Sale {sale.invoice_number} processed successfully! Receipt ready.")
        return redirect('inventory:sale_receipt', sale_id=sale.id)

    except ValueError as ve:
        messages.error(request, str(ve))
        return redirect('inventory:pos_terminal')
    except Exception as e:
        messages.error(request, f"Error processing sale: {str(e)}")
        return redirect('inventory:pos_terminal')


@require_general_gateway
def sale_receipt_view(request, sale_id):
    """Printable official invoice and POS thermal slip (customer & merchant copy)."""
    sale = get_object_or_404(Sale.objects.select_related('branch', 'customer'), id=sale_id)
    items = sale.items.select_related('product', 'product__category')
    splits = sale.splits.all()
    debt_repayments = sale.debt_repayments.all().order_by('created_at')
    
    return render(request, 'inventory/pos/receipt.html', {
        'sale': sale,
        'items': items,
        'splits': splits,
        'debt_repayments': debt_repayments,
    })

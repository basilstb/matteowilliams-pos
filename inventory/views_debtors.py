from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from decimal import Decimal

from .models import (
    Branch, Customer, Sale, PaymentSplit, DebtRepayment, AuditLog
)
from .decorators import require_general_gateway, require_roles
from .views_auth import get_client_ip


@require_general_gateway
@require_roles('CASHIER', 'MANAGER', 'OWNER')
def debtors_list_view(request):
    """Debtors Hub: View all customers owing money, filter by branch/status, and collect repayments."""
    user_role = request.session.get('user_role')
    branch_id = request.session.get('branch_id')
    
    # Query sales that have outstanding debt
    debt_sales = Sale.objects.filter(balance_owed__gt=Decimal('0.00')).select_related('branch', 'customer')
    
    # Cashiers can only view their branch's debtors; Owner & Manager can toggle or view all
    branch_filter = request.GET.get('branch', 'all')
    if user_role == 'CASHIER' and branch_id:
        debt_sales = debt_sales.filter(branch_id=branch_id)
        selected_branch = Branch.objects.filter(id=branch_id).first()
    elif branch_filter != 'all' and branch_filter.isdigit():
        debt_sales = debt_sales.filter(branch_id=int(branch_filter))
        selected_branch = Branch.objects.filter(id=int(branch_filter)).first()
    else:
        selected_branch = None

    # Status filter
    status_filter = request.GET.get('status', 'all')
    today = timezone.now().date()
    
    if status_filter == 'partial':
        debt_sales = debt_sales.filter(payment_status='PARTIAL_DEBT')
    elif status_filter == 'full_credit':
        debt_sales = debt_sales.filter(payment_status='FULL_DEBT')
    elif status_filter == 'overdue':
        debt_sales = debt_sales.filter(debt_due_date__lt=today)

    # Search filter
    search_q = request.GET.get('q', '').strip()
    if search_q:
        debt_sales = debt_sales.filter(
            customer_name_snapshot__icontains=search_q
        ) | debt_sales.filter(
            customer_phone_snapshot__icontains=search_q
        ) | debt_sales.filter(
            invoice_number__icontains=search_q
        )

    # Metrics
    all_debt_sales_for_stats = Sale.objects.filter(balance_owed__gt=Decimal('0.00'))
    if user_role == 'CASHIER' and branch_id:
        all_debt_sales_for_stats = all_debt_sales_for_stats.filter(branch_id=branch_id)
        
    total_debt_outstanding = sum(s.balance_owed for s in all_debt_sales_for_stats) or Decimal('0.00')
    total_debtors_count = all_debt_sales_for_stats.count()
    overdue_count = all_debt_sales_for_stats.filter(debt_due_date__lt=today).count()
    
    # Recent repayments
    recent_repayments = DebtRepayment.objects.select_related('sale', 'customer').order_by('-created_at')[:8]
    if user_role == 'CASHIER' and branch_id:
        recent_repayments = recent_repayments.filter(sale__branch_id=branch_id)

    return render(request, 'inventory/debtors/list.html', {
        'debt_sales': debt_sales.order_by('-created_at'),
        'total_debt_outstanding': total_debt_outstanding,
        'total_debtors_count': total_debtors_count,
        'overdue_count': overdue_count,
        'branches': Branch.objects.filter(is_active=True),
        'selected_branch': selected_branch,
        'branch_filter': branch_filter,
        'status_filter': status_filter,
        'search_q': search_q,
        'recent_repayments': recent_repayments,
        'today': today,
    })


@require_general_gateway
@require_roles('CASHIER', 'MANAGER', 'OWNER')
def record_debt_repayment_view(request, sale_id):
    """Records installment or full debt payment against a specific invoice."""
    sale = get_object_or_404(Sale.objects.select_related('branch', 'customer'), id=sale_id)
    actor_name = request.session.get('actor_name', 'Cashier')
    user_role = request.session.get('user_role', 'CASHIER')
    
    if sale.balance_owed <= Decimal('0.00'):
        messages.info(request, f"Invoice {sale.invoice_number} is already paid in full!")
        return redirect('inventory:debtors_list')

    if request.method == 'POST':
        try:
            repay_amount = Decimal(request.POST.get('repay_amount', '0.00') or '0.00')
            payment_method = request.POST.get('payment_method', 'CASH')
            reference_note = request.POST.get('reference_note', '').strip()
            
            if repay_amount <= Decimal('0.00'):
                raise ValueError("Repayment amount must be greater than ₦0.00.")
                
            if repay_amount > sale.balance_owed:
                raise ValueError(f"Repayment amount (₦{repay_amount:,.2f}) cannot exceed outstanding debt of ₦{sale.balance_owed:,.2f}.")

            with transaction.atomic():
                bal_before = sale.balance_owed
                bal_after = bal_before - repay_amount
                
                # Generate unique Debt Repayment Receipt code
                date_str = timezone.now().strftime('%Y%m%d')
                repay_count = DebtRepayment.objects.filter(created_at__date=timezone.now().date()).count() + 1
                receipt_no = f"DRP-{sale.branch.code}-{date_str}-{repay_count:04d}"

                repayment = DebtRepayment.objects.create(
                    receipt_number=receipt_no,
                    sale=sale,
                    customer=sale.customer,
                    amount_paid=repay_amount,
                    payment_method=payment_method,
                    balance_before=bal_before,
                    balance_after=bal_after,
                    received_by=actor_name,
                    received_by_role=user_role,
                    reference_note=reference_note or f"Debt payment via {payment_method}",
                    created_at=timezone.now()
                )

                # Update sale balances
                sale.amount_paid += repay_amount
                sale.balance_owed = bal_after
                sale.update_debt_status()

                # Audit Log
                AuditLog.objects.create(
                    branch=sale.branch,
                    user_role=user_role,
                    actor_name=actor_name,
                    action_type='DEBT_REPAID',
                    details=f"Recorded ₦{repay_amount:,.2f} debt payment for Invoice {sale.invoice_number}. New Balance: ₦{bal_after:,.2f}",
                    ip_address=get_client_ip(request),
                    created_at=timezone.now()
                )

            messages.success(request, f"₦{repay_amount:,.2f} payment successfully credited to Invoice {sale.invoice_number}! Receipt: {receipt_no}")
            return redirect('inventory:debt_repayment_receipt', repayment_id=repayment.id)

        except ValueError as ve:
            messages.error(request, str(ve))
        except Exception as e:
            messages.error(request, f"Error processing debt payment: {str(e)}")

    return render(request, 'inventory/debtors/record_payment.html', {
        'sale': sale,
        'now': timezone.now(),
    })


@require_general_gateway
def debt_repayment_receipt_view(request, repayment_id):
    """Printable official Debt Repayment Slip / Acknowledgment."""
    repayment = get_object_or_404(
        DebtRepayment.objects.select_related('sale', 'sale__branch', 'customer'),
        id=repayment_id
    )
    return render(request, 'inventory/debtors/repayment_receipt.html', {
        'repayment': repayment,
        'sale': repayment.sale,
    })


@require_general_gateway
def sale_debt_history_view(request, sale_id):
    """View complete debt repayment timeline and installment receipts for a sale."""
    sale = get_object_or_404(Sale.objects.select_related('branch', 'customer'), id=sale_id)
    repayments = sale.debt_repayments.all().order_by('-created_at')
    splits = sale.splits.all()
    
    return render(request, 'inventory/debtors/sale_history.html', {
        'sale': sale,
        'repayments': repayments,
        'splits': splits,
    })

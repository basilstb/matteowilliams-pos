from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum
from decimal import Decimal

from .models import (
    Branch, Category, Product, BranchStock, Customer,
    Sale, PaymentSplit, DebtRepayment, AuditLog
)
from .decorators import require_general_gateway, require_roles, require_branch
from .views_auth import get_client_ip


@require_general_gateway
@require_roles('MANAGER', 'OWNER')
@require_branch
def branch_dashboard_view(request):
    """Branch Manager Dashboard for operational oversight, stock monitoring, and debt collection."""
    branch_id = request.session.get('branch_id')
    user_role = request.session.get('user_role')
    
    if user_role == 'OWNER' and not branch_id:
        branch = Branch.objects.filter(is_active=True).first()
    else:
        branch = get_object_or_404(Branch, id=branch_id)

    today = timezone.now().date()
    today_sales = Sale.objects.filter(branch=branch, created_at__date=today)
    
    today_revenue = today_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    today_collected = today_sales.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    today_debt_issued = today_sales.aggregate(total=Sum('balance_owed'))['total'] or Decimal('0.00')
    
    # Split collections for today
    today_splits = PaymentSplit.objects.filter(sale__branch=branch, created_at__date=today)
    cash_today = today_splits.filter(method='CASH').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    transfer_today = today_splits.filter(method='TRANSFER').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    pos_today = today_splits.filter(method='POS').aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

    # Add today's debt repayments
    today_repayments = DebtRepayment.objects.filter(sale__branch=branch, created_at__date=today)
    repaid_cash = today_repayments.filter(payment_method='CASH').aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    repaid_transfer = today_repayments.filter(payment_method='TRANSFER').aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    repaid_pos = today_repayments.filter(payment_method='POS').aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    
    total_cash_drawer = cash_today + repaid_cash
    total_transfer_verified = transfer_today + repaid_transfer
    total_pos_terminal = pos_today + repaid_pos

    # Stocks
    stocks = BranchStock.objects.filter(branch=branch).select_related('product', 'product__category')
    low_stock_items = [s for s in stocks if s.quantity <= s.reorder_level]

    # Branch Debtors
    active_branch_debtors = Sale.objects.filter(branch=branch, balance_owed__gt=Decimal('0.00')).select_related('customer')[:8]

    return render(request, 'inventory/branch/dashboard.html', {
        'branch': branch,
        'today_revenue': today_revenue,
        'today_collected': today_collected,
        'today_debt_issued': today_debt_issued,
        'total_cash_drawer': total_cash_drawer,
        'total_transfer_verified': total_transfer_verified,
        'total_pos_terminal': total_pos_terminal,
        'today_sales_count': today_sales.count(),
        'stocks': stocks,
        'low_stock_items': low_stock_items,
        'active_branch_debtors': active_branch_debtors,
        'now': timezone.now(),
    })


@require_general_gateway
@require_roles('MANAGER', 'OWNER')
@require_branch
def branch_stock_view(request):
    """View and restock electronics products at this branch."""
    branch_id = request.session.get('branch_id')
    user_role = request.session.get('user_role')
    
    if user_role == 'OWNER' and not branch_id:
        branch = Branch.objects.filter(is_active=True).first()
    else:
        branch = get_object_or_404(Branch, id=branch_id)

    stocks = BranchStock.objects.filter(branch=branch).select_related('product', 'product__category').order_by('product__name')

    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        qty_to_add = int(request.POST.get('quantity_to_add', 0))
        restock_note = request.POST.get('restock_note', 'Consignment received at Onitsha shop')
        
        if product_id and qty_to_add > 0:
            stock_record = get_object_or_404(BranchStock, branch=branch, product_id=product_id)
            stock_record.quantity += qty_to_add
            stock_record.save()
            
            actor_name = request.session.get('actor_name', 'Manager')
            AuditLog.objects.create(
                branch=branch,
                user_role=user_role,
                actor_name=actor_name,
                action_type='STOCK_RESTOCKED',
                details=f"Added {qty_to_add} {stock_record.product.unit} to {stock_record.product.name}. New total: {stock_record.quantity}. Note: {restock_note}",
                ip_address=get_client_ip(request),
                created_at=timezone.now()
            )
            messages.success(request, f"Successfully restocked {qty_to_add} units of {stock_record.product.name}!")
            return redirect('inventory:branch_stock')

    return render(request, 'inventory/branch/stock.html', {
        'branch': branch,
        'stocks': stocks,
    })

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum, Count, Q
from decimal import Decimal

from .models import (
    Branch, Category, Product, BranchStock, Customer,
    Sale, PaymentSplit, DebtRepayment, AuditLog, SystemSettings
)
from .decorators import require_general_gateway, require_roles
from .views_auth import get_client_ip


@require_general_gateway
@require_roles('OWNER')
def owner_dashboard_view(request):
    """Central Owner Command Center with consolidated cross-branch financials."""
    settings = SystemSettings.get_settings()
    branches = Branch.objects.all().order_by('id')
    
    # Financial Aggregations across all branches
    all_sales = Sale.objects.all()
    total_revenue = all_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
    total_debt_owed = all_sales.aggregate(total=Sum('balance_owed'))['total'] or Decimal('0.00')
    total_collected = all_sales.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    
    # Splits breakdown
    splits_summary = PaymentSplit.objects.values('method').annotate(total=Sum('amount'))
    splits_dict = {item['method']: item['total'] for item in splits_summary}
    cash_collected = splits_dict.get('CASH', Decimal('0.00'))
    transfer_collected = splits_dict.get('TRANSFER', Decimal('0.00'))
    pos_collected = splits_dict.get('POS', Decimal('0.00'))
    
    # Add subsequent debt repayments
    all_repayments = DebtRepayment.objects.all()
    repayments_by_method = all_repayments.values('payment_method').annotate(total=Sum('amount_paid'))
    for r in repayments_by_method:
        m = r['payment_method']
        if m == 'CASH':
            cash_collected += r['total']
        elif m == 'TRANSFER':
            transfer_collected += r['total']
        elif m == 'POS':
            pos_collected += r['total']

    # Total Debt Repayments collected to date
    total_debt_recovered = all_repayments.aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')
    
    # Gross Profit Estimation: (Sale Items Selling Price - Product Cost Price)
    # Fast estimate
    estimated_profit = Decimal('0.00')
    sale_items = Sale.objects.values('items__quantity', 'items__unit_price', 'items__product__cost_price')
    for si in sale_items:
        qty = si['items__quantity'] or 0
        uprice = si['items__unit_price'] or Decimal('0.00')
        cost = si['items__product__cost_price'] or Decimal('0.00')
        estimated_profit += (uprice - cost) * qty

    # Per-Branch performance summary
    branch_summaries = []
    for b in branches:
        b_sales = Sale.objects.filter(branch=b)
        b_rev = b_sales.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        b_debt = b_sales.aggregate(total=Sum('balance_owed'))['total'] or Decimal('0.00')
        b_stock_count = BranchStock.objects.filter(branch=b).aggregate(total=Sum('quantity'))['total'] or 0
        
        branch_summaries.append({
            'branch': b,
            'is_locked': b.is_currently_locked(),
            'revenue': b_rev,
            'debt': b_debt,
            'stock_count': b_stock_count,
            'sales_count': b_sales.count(),
        })

    # Recent High-Priority Audit Logs
    recent_audits = AuditLog.objects.all().order_by('-created_at')[:10]

    return render(request, 'inventory/owner/dashboard.html', {
        'settings': settings,
        'branches': branches,
        'branch_summaries': branch_summaries,
        'total_revenue': total_revenue,
        'total_debt_owed': total_debt_owed,
        'total_collected': total_collected,
        'cash_collected': cash_collected,
        'transfer_collected': transfer_collected,
        'pos_collected': pos_collected,
        'total_debt_recovered': total_debt_recovered,
        'estimated_profit': estimated_profit,
        'recent_audits': recent_audits,
        'now': timezone.now(),
    })


@require_general_gateway
@require_roles('OWNER')
def owner_branches_view(request):
    """Manage existing branches, reset PINs, unlock terminals, and view security locks."""
    branches = Branch.objects.all().order_by('id')
    for b in branches:
        b.is_currently_locked()

    return render(request, 'inventory/owner/branches.html', {
        'branches': branches,
        'now': timezone.now(),
    })


@require_general_gateway
@require_roles('OWNER')
def owner_create_branch_view(request):
    """Owner feature: Create additional shops/branches at any location."""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().upper()
        location = request.POST.get('location', '').strip()
        phone = request.POST.get('phone', '').strip()
        cashier_pin = request.POST.get('cashier_pin', '').strip()
        manager_pin = request.POST.get('manager_pin', '').strip()

        if not name or not code or not cashier_pin or not manager_pin:
            messages.error(request, "Branch name, unique code, cashier PIN, and manager PIN are all required.")
            return render(request, 'inventory/owner/create_branch.html')

        if Branch.objects.filter(code=code).exists():
            messages.error(request, f"Branch code '{code}' already exists. Please choose a distinct code.")
            return render(request, 'inventory/owner/create_branch.html')

        branch = Branch.objects.create(
            name=name,
            code=code,
            location=location,
            phone=phone,
            cashier_pin=cashier_pin,
            manager_pin=manager_pin,
            is_active=True
        )

        # Initialize stock entries for all active products for the new branch
        products = Product.objects.filter(is_active=True)
        for prod in products:
            BranchStock.objects.create(
                branch=branch,
                product=prod,
                quantity=0,
                reorder_level=4
            )

        AuditLog.objects.create(
            branch=branch,
            user_role='OWNER',
            actor_name='Owner',
            action_type='BRANCH_CREATED',
            details=f"New branch created: {branch.name} ({branch.code}) at {branch.location}",
            ip_address=get_client_ip(request)
        )

        messages.success(request, f"New branch '{branch.name}' ({branch.code}) successfully established with assigned PINs!")
        return redirect('inventory:owner_branches')

    return render(request, 'inventory/owner/create_branch.html')


@require_general_gateway
@require_roles('OWNER')
def owner_edit_branch_view(request, branch_id):
    """Edit branch details, reset cashier/manager PINs, and manage locks."""
    branch = get_object_or_404(Branch, id=branch_id)
    
    if request.method == 'POST':
        branch.name = request.POST.get('name', branch.name).strip()
        branch.location = request.POST.get('location', branch.location).strip()
        branch.phone = request.POST.get('phone', branch.phone).strip()
        
        new_cashier_pin = request.POST.get('cashier_pin', '').strip()
        new_manager_pin = request.POST.get('manager_pin', '').strip()
        if new_cashier_pin:
            branch.cashier_pin = new_cashier_pin
        if new_manager_pin:
            branch.manager_pin = new_manager_pin
            
        is_active = request.POST.get('is_active') == 'on'
        branch.is_active = is_active
        
        branch.save()
        
        AuditLog.objects.create(
            branch=branch,
            user_role='OWNER',
            actor_name='Owner',
            action_type='BRANCH_UPDATED',
            details=f"Branch {branch.name} settings updated. PINs reconfigured.",
            ip_address=get_client_ip(request)
        )
        messages.success(request, f"Branch '{branch.name}' settings saved.")
        return redirect('inventory:owner_branches')

    return render(request, 'inventory/owner/edit_branch.html', {
        'branch': branch,
    })


@require_general_gateway
@require_roles('OWNER')
def owner_settings_view(request):
    """Update General Gatekeeper password, Master Owner PIN, and business metadata."""
    settings = SystemSettings.get_settings()
    
    if request.method == 'POST':
        new_gen_pass = request.POST.get('general_password', '').strip()
        new_owner_pin = request.POST.get('owner_pin', '').strip()
        new_owner_pass = request.POST.get('owner_password', '').strip()
        b_name = request.POST.get('business_name', '').strip()
        b_tagline = request.POST.get('business_tagline', '').strip()
        b_phone = request.POST.get('business_phone', '').strip()
        b_addr = request.POST.get('business_address', '').strip()

        if new_gen_pass:
            settings.general_password = new_gen_pass
        if new_owner_pin:
            settings.owner_pin = new_owner_pin
        if new_owner_pass:
            settings.owner_password = new_owner_pass
            
        if b_name:
            settings.business_name = b_name
        if b_tagline:
            settings.business_tagline = b_tagline
        if b_phone:
            settings.business_phone = b_phone
        if b_addr:
            settings.business_address = b_addr
            
        settings.save()
        
        AuditLog.objects.create(
            user_role='OWNER',
            actor_name='Owner',
            action_type='SYSTEM_SETTINGS_UPDATED',
            details="System general password and business configuration updated",
            ip_address=get_client_ip(request)
        )
        messages.success(request, "System security & business configuration successfully updated!")
        return redirect('inventory:owner_settings')

    return render(request, 'inventory/owner/settings.html', {
        'settings': settings,
    })


@require_general_gateway
@require_roles('OWNER')
def owner_audit_logs_view(request):
    """Comprehensive immutable audit log with exact timestamps, roles, and event tracking."""
    logs = AuditLog.objects.all().order_by('-created_at')
    
    action_type = request.GET.get('action_type')
    if action_type:
        logs = logs.filter(action_type=action_type)
        
    branch_id = request.GET.get('branch_id')
    if branch_id and branch_id.isdigit():
        logs = logs.filter(branch_id=int(branch_id))

    return render(request, 'inventory/owner/audit_logs.html', {
        'logs': logs[:100],
        'branches': Branch.objects.all(),
        'action_type': action_type,
        'branch_id': branch_id,
    })


@require_general_gateway
def role_matrix_view(request):
    """Role boundaries and permissions reference guide."""
    return render(request, 'inventory/owner/role_matrix.html')

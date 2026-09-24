from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum
from decimal import Decimal

from .models import Branch, BranchStock, Product, Expense, AuditLog
from .decorators import require_general_gateway, require_roles, require_branch
from .views_auth import get_client_ip


@require_general_gateway
@require_roles('MANAGER', 'OWNER')
@require_branch
def expense_list_view(request):
    """List all expenses & damages logged at this branch."""
    branch_id = request.session.get('branch_id')
    user_role = request.session.get('user_role')

    if user_role == 'OWNER' and not branch_id:
        branch = Branch.objects.filter(is_active=True).first()
    else:
        branch = get_object_or_404(Branch, id=branch_id)

    expenses = Expense.objects.filter(branch=branch).select_related('product')

    # Summary totals
    total_expenses = expenses.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')
    damaged_total  = expenses.filter(expense_type='DAMAGED_GOODS').aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    # Filter by type
    filter_type = request.GET.get('type', 'all')
    if filter_type != 'all':
        expenses = expenses.filter(expense_type=filter_type)

    # Branch stocks for the damaged-goods dropdown
    stocks = BranchStock.objects.filter(branch=branch, product__is_active=True).select_related('product')

    return render(request, 'inventory/expenses/list.html', {
        'branch': branch,
        'expenses': expenses[:80],
        'stocks': stocks,
        'total_expenses': total_expenses,
        'damaged_total': damaged_total,
        'expense_types': Expense.TYPE_CHOICES,
        'filter_type': filter_type,
        'user_role': user_role,
    })


@require_general_gateway
@require_roles('MANAGER', 'OWNER')
@require_branch
def record_expense_view(request):
    """POST handler: record a new expense or damage write-off."""
    if request.method != 'POST':
        return redirect('inventory:expense_list')

    branch_id = request.session.get('branch_id')
    user_role = request.session.get('user_role')
    actor_name = request.session.get('actor_name', 'Manager')

    if user_role == 'OWNER' and not branch_id:
        branch = Branch.objects.filter(is_active=True).first()
    else:
        branch = get_object_or_404(Branch, id=branch_id)

    try:
        expense_type   = request.POST.get('expense_type', 'OPERATIONAL').strip()
        title          = request.POST.get('title', '').strip()
        amount_str     = request.POST.get('amount', '0').strip() or '0'
        notes          = request.POST.get('notes', '').strip()
        product_id     = request.POST.get('product_id', '').strip()
        qty_damaged    = int(request.POST.get('quantity_damaged', '0') or '0')

        if not title:
            messages.error(request, "Please enter a title / description for this expense.")
            return redirect('inventory:expense_list')

        amount = Decimal(amount_str)
        if amount <= Decimal('0.00'):
            messages.error(request, "Expense amount must be greater than zero.")
            return redirect('inventory:expense_list')

        # Reference number
        count = Expense.objects.filter(branch=branch).count() + 1
        date_str = timezone.now().strftime('%Y%m%d')
        ref = f"EXP-{branch.code}-{date_str}-{count:04d}"

        # Linked product (optional, for damaged goods)
        product = None
        if product_id and product_id.isdigit():
            product = Product.objects.filter(id=int(product_id)).first()

        # If damaged goods — write off stock
        if expense_type == 'DAMAGED_GOODS' and product and qty_damaged > 0:
            stock = BranchStock.objects.filter(branch=branch, product=product).first()
            if stock:
                if stock.quantity < qty_damaged:
                    messages.error(
                        request,
                        f"Cannot write off {qty_damaged} {product.unit} of {product.name}. "
                        f"Branch only has {stock.quantity} in stock."
                    )
                    return redirect('inventory:expense_list')
                stock.quantity -= qty_damaged
                stock.save()

        expense = Expense.objects.create(
            reference=ref,
            branch=branch,
            expense_type=expense_type,
            title=title,
            amount=amount,
            product=product,
            quantity_damaged=qty_damaged if (expense_type == 'DAMAGED_GOODS') else 0,
            notes=notes,
            recorded_by=actor_name,
            recorded_by_role=user_role,
        )

        AuditLog.objects.create(
            branch=branch,
            user_role=user_role,
            actor_name=actor_name,
            action_type='EXPENSE_RECORDED',
            details=(
                f"Expense {expense.reference} | {expense.get_expense_type_display()} | "
                f"₦{amount:,.2f} | {title}"
                + (f" | Product: {product.name} x{qty_damaged}" if product and qty_damaged > 0 else "")
            ),
        )

        messages.success(request, f"Expense '{title}' recorded successfully (Ref: {ref}).")
        return redirect('inventory:expense_list')

    except Exception as e:
        messages.error(request, f"Error recording expense: {str(e)}")
        return redirect('inventory:expense_list')

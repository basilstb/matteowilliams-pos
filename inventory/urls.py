from django.urls import path
from . import views_auth, views_pos, views_debtors, views_owner, views_branch, views_expenses

app_name = 'inventory'

urlpatterns = [
    # Gateway & Authentication
    path('', views_auth.general_login_view, name='root'),
    path('login/', views_auth.general_login_view, name='general_login'),
    path('portal/', views_auth.portal_hub_view, name='portal_hub'),
    path('owner/login/', views_auth.owner_login_view, name='owner_login'),
    path('branch/<int:branch_id>/login/', views_auth.branch_login_view, name='branch_login'),
    path('branch/<int:branch_id>/unlock/', views_auth.unlock_branch_view, name='unlock_branch'),
    path('logout/', views_auth.logout_view, name='logout'),

    # POS Terminal & Sales
    path('pos/', views_pos.pos_terminal_view, name='pos_terminal'),
    path('pos/process/', views_pos.process_sale_view, name='process_sale'),
    path('pos/receipt/<int:sale_id>/', views_pos.sale_receipt_view, name='sale_receipt'),

    # Debtors Management & Repayment
    path('debtors/', views_debtors.debtors_list_view, name='debtors_list'),
    path('debtors/<int:sale_id>/repay/', views_debtors.record_debt_repayment_view, name='record_debt_repayment'),
    path('debtors/receipt/<int:repayment_id>/', views_debtors.debt_repayment_receipt_view, name='debt_repayment_receipt'),
    path('debtors/<int:sale_id>/history/', views_debtors.sale_debt_history_view, name='sale_debt_history'),

    # Branch Manager
    path('branch/dashboard/', views_branch.branch_dashboard_view, name='branch_dashboard'),
    path('branch/stock/', views_branch.branch_stock_view, name='branch_stock'),

    # Expenses & Damage Log
    path('expenses/', views_expenses.expense_list_view, name='expense_list'),
    path('expenses/record/', views_expenses.record_expense_view, name='record_expense'),

    # Owner Central Command
    path('owner/dashboard/', views_owner.owner_dashboard_view, name='owner_dashboard'),
    path('owner/branches/', views_owner.owner_branches_view, name='owner_branches'),
    path('owner/branches/new/', views_owner.owner_create_branch_view, name='owner_create_branch'),
    path('owner/branches/<int:branch_id>/edit/', views_owner.owner_edit_branch_view, name='owner_edit_branch'),
    path('owner/settings/', views_owner.owner_settings_view, name='owner_settings'),
    path('owner/audit/', views_owner.owner_audit_logs_view, name='owner_audit_logs'),

    # Role Boundaries Guide
    path('roles/', views_owner.role_matrix_view, name='role_matrix'),
]

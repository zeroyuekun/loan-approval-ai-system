import datetime
import re
from decimal import Decimal, InvalidOperation

from django.contrib.auth import authenticate
from rest_framework import serializers

from .models import CustomerProfile, CustomUser


class EncryptedDateField(serializers.DateField):
    """Accepts date input, stores as ISO string in EncryptedCharField."""

    def to_internal_value(self, data):
        # Validate via parent, then convert to ISO string for storage
        date_obj = super().to_internal_value(data)
        return date_obj.isoformat()

    def to_representation(self, value):
        if not value:
            return None
        if isinstance(value, str):
            try:
                return datetime.date.fromisoformat(value).isoformat()
            except (ValueError, TypeError):
                return value
        return super().to_representation(value)


class EncryptedDecimalField(serializers.DecimalField):
    """Accepts decimal input, stores as string in EncryptedCharField."""

    def to_internal_value(self, data):
        # Validate via parent, then convert to string for storage
        decimal_val = super().to_internal_value(data)
        return str(decimal_val)

    def to_representation(self, value):
        if value is None or value == "":
            return None
        if isinstance(value, str):
            try:
                value = Decimal(value)
            except (InvalidOperation, TypeError):
                return value
        return super().to_representation(value)


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=12)
    password2 = serializers.CharField(write_only=True, min_length=12)

    class Meta:
        model = CustomUser
        fields = ("username", "email", "password", "password2", "first_name", "last_name")

    def validate(self, data):
        if data["password"] != data["password2"]:
            raise serializers.ValidationError({"password2": "Passwords do not match."})
        pw = data["password"]
        if not re.search(r"[A-Z]", pw):
            raise serializers.ValidationError({"password": "Password must contain at least one uppercase letter."})
        if not re.search(r"[a-z]", pw):
            raise serializers.ValidationError({"password": "Password must contain at least one lowercase letter."})
        if not re.search(r"[0-9]", pw):
            raise serializers.ValidationError({"password": "Password must contain at least one digit."})
        return data

    def create(self, validated_data):
        validated_data.pop("password2")
        password = validated_data.pop("password")
        user = CustomUser(**validated_data, role="customer")
        user.set_password(password)
        user.save()
        return user


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        username_or_email = data["username"]
        # Allow login with email: resolve to username first
        if "@" in username_or_email:
            try:
                user_obj = CustomUser.objects.get(email=username_or_email)
                username_or_email = user_obj.username
            except CustomUser.DoesNotExist as err:
                raise serializers.ValidationError("Invalid credentials.") from err
        user = authenticate(username=username_or_email, password=data["password"])
        if not user:
            raise serializers.ValidationError("Invalid credentials.")
        if not user.is_active:
            raise serializers.ValidationError("User account is disabled.")
        data["user"] = user
        return data


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ("id", "username", "email", "role", "first_name", "last_name", "created_at")
        read_only_fields = ("id", "username", "role", "created_at")


def _mask_id_number(value):
    """Show only last 4 characters of an ID number."""
    if not value or len(value) <= 4:
        return value
    return "****" + value[-4:]


class CustomerProfileSerializer(serializers.ModelSerializer):
    account_tenure_years = serializers.IntegerField(read_only=True)
    loyalty_tier = serializers.CharField(read_only=True)
    num_products = serializers.IntegerField(read_only=True)
    is_profile_complete = serializers.BooleanField(read_only=True)
    missing_profile_fields = serializers.ListField(child=serializers.CharField(), read_only=True)
    primary_id_number_masked = serializers.SerializerMethodField()
    secondary_id_number_masked = serializers.SerializerMethodField()
    total_assets = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    total_monthly_liabilities = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    # Encrypted PII fields — accept native types, store as encrypted strings
    date_of_birth = EncryptedDateField(required=False, allow_null=True)
    gross_annual_income = EncryptedDecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    other_income = EncryptedDecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    partner_annual_income = EncryptedDecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)

    class Meta:
        model = CustomerProfile
        fields = (
            "id",
            # Profile completeness
            "is_profile_complete",
            "missing_profile_fields",
            # Personal details
            "date_of_birth",
            "phone",
            "address_line_1",
            "address_line_2",
            "suburb",
            "state",
            "postcode",
            "marital_status",
            # Identity & compliance
            "residency_status",
            "primary_id_type",
            "primary_id_number",
            "secondary_id_type",
            "secondary_id_number",
            "primary_id_number_masked",
            "secondary_id_number_masked",
            "tax_file_number_provided",
            "is_politically_exposed",
            # Employment
            "employer_name",
            "occupation",
            "industry",
            "employment_status",
            "years_in_current_role",
            "previous_employer",
            # Income
            "gross_annual_income",
            "other_income",
            "other_income_source",
            "partner_annual_income",
            # Assets
            "estimated_property_value",
            "vehicle_value",
            "savings_other_institutions",
            "investment_value",
            "superannuation_balance",
            # Liabilities
            "other_loan_repayments_monthly",
            "other_credit_card_limits",
            "rent_or_board_monthly",
            # Living situation
            "housing_situation",
            "time_at_current_address_years",
            "number_of_dependants",
            "previous_suburb",
            "previous_state",
            "previous_postcode",
            # Contact
            "preferred_contact_method",
            # Computed (read-only)
            "total_assets",
            "total_monthly_liabilities",
            # Banking (read-only for customer)
            "account_tenure_years",
            "loyalty_tier",
            "num_products",
            "savings_balance",
            "checking_balance",
            "has_credit_card",
            "has_mortgage",
            "has_auto_loan",
            "on_time_payment_pct",
            "previous_loans_repaid",
            # Timestamps
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "is_profile_complete",
            "missing_profile_fields",
            # Computed
            "total_assets",
            "total_monthly_liabilities",
            # Banking — managed by the bank
            "account_tenure_years",
            "loyalty_tier",
            "num_products",
            "savings_balance",
            "checking_balance",
            "has_credit_card",
            "has_mortgage",
            "has_auto_loan",
            "on_time_payment_pct",
            "previous_loans_repaid",
            "created_at",
            "updated_at",
        )

    def validate(self, data):
        warnings = []

        # Soft warning: short tenure at current role — previous employer recommended
        years_in_role = data.get("years_in_current_role")
        if years_in_role is not None and years_in_role < 2:
            if not data.get("previous_employer") and not getattr(self.instance, "previous_employer", None):
                warnings.append("years_in_current_role is less than 2; providing previous_employer is recommended.")

        # Soft warning: short time at current address — previous address details recommended
        time_at_address = data.get("time_at_current_address_years")
        if time_at_address is not None and time_at_address < 3:
            instance = self.instance
            missing_prev = []
            for field in ("previous_suburb", "previous_state", "previous_postcode"):
                if not data.get(field) and not getattr(instance, field, None):
                    missing_prev.append(field)
            if missing_prev:
                warnings.append(
                    f"time_at_current_address_years is less than 3; providing {', '.join(missing_prev)} is recommended."
                )

        if warnings:
            data["_warnings"] = warnings

        return data

    def get_primary_id_number_masked(self, obj):
        return _mask_id_number(obj.primary_id_number)

    def get_secondary_id_number_masked(self, obj):
        return _mask_id_number(obj.secondary_id_number)


class StaffCustomerDetailSerializer(serializers.ModelSerializer):
    """Read-only serializer for staff viewing any customer's full profile."""

    user = UserSerializer(read_only=True)
    primary_id_number = serializers.SerializerMethodField()
    secondary_id_number = serializers.SerializerMethodField()
    total_assets = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    total_monthly_liabilities = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    # Encrypted PII fields — present as native types in API responses
    date_of_birth = EncryptedDateField(read_only=True)
    gross_annual_income = EncryptedDecimalField(max_digits=12, decimal_places=2, read_only=True)
    other_income = EncryptedDecimalField(max_digits=12, decimal_places=2, read_only=True)
    partner_annual_income = EncryptedDecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = CustomerProfile
        fields = (
            "id",
            "user",
            # Personal details
            "date_of_birth",
            "phone",
            "address_line_1",
            "address_line_2",
            "suburb",
            "state",
            "postcode",
            "marital_status",
            # Identity & compliance
            "residency_status",
            "primary_id_type",
            "primary_id_number",
            "secondary_id_type",
            "secondary_id_number",
            "tax_file_number_provided",
            "is_politically_exposed",
            # Employment
            "employer_name",
            "occupation",
            "industry",
            "employment_status",
            "years_in_current_role",
            "previous_employer",
            # Income
            "gross_annual_income",
            "other_income",
            "other_income_source",
            "partner_annual_income",
            # Assets
            "estimated_property_value",
            "vehicle_value",
            "savings_other_institutions",
            "investment_value",
            "superannuation_balance",
            # Liabilities
            "other_loan_repayments_monthly",
            "other_credit_card_limits",
            "rent_or_board_monthly",
            # Living situation
            "housing_situation",
            "time_at_current_address_years",
            "number_of_dependants",
            "previous_suburb",
            "previous_state",
            "previous_postcode",
            # Contact
            "preferred_contact_method",
            # Computed (read-only)
            "total_assets",
            "total_monthly_liabilities",
            # Banking
            "account_tenure_years",
            "loyalty_tier",
            "num_products",
            "savings_balance",
            "checking_balance",
            "has_credit_card",
            "has_mortgage",
            "has_auto_loan",
            "on_time_payment_pct",
            "previous_loans_repaid",
            # Timestamps
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_primary_id_number(self, obj):
        return _mask_id_number(obj.primary_id_number)

    def get_secondary_id_number(self, obj):
        return _mask_id_number(obj.secondary_id_number)


class AdminCustomerProfileUpdateSerializer(serializers.ModelSerializer):
    """Serializer for admin to update any customer's profile fields."""

    user = UserSerializer(read_only=True)
    primary_id_number_masked = serializers.SerializerMethodField()
    secondary_id_number_masked = serializers.SerializerMethodField()
    total_assets = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    total_monthly_liabilities = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    # Encrypted PII fields — accept native types, store as encrypted strings
    date_of_birth = EncryptedDateField(required=False, allow_null=True)
    gross_annual_income = EncryptedDecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    other_income = EncryptedDecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)
    partner_annual_income = EncryptedDecimalField(max_digits=12, decimal_places=2, required=False, allow_null=True)

    class Meta:
        model = CustomerProfile
        fields = (
            "id",
            "user",
            # Personal details
            "date_of_birth",
            "phone",
            "address_line_1",
            "address_line_2",
            "suburb",
            "state",
            "postcode",
            "marital_status",
            # Identity & compliance
            "residency_status",
            "primary_id_type",
            "primary_id_number",
            "secondary_id_type",
            "secondary_id_number",
            "primary_id_number_masked",
            "secondary_id_number_masked",
            "tax_file_number_provided",
            "is_politically_exposed",
            # Employment
            "employer_name",
            "occupation",
            "industry",
            "employment_status",
            "years_in_current_role",
            "previous_employer",
            # Income
            "gross_annual_income",
            "other_income",
            "other_income_source",
            "partner_annual_income",
            # Assets
            "estimated_property_value",
            "vehicle_value",
            "savings_other_institutions",
            "investment_value",
            "superannuation_balance",
            # Liabilities
            "other_loan_repayments_monthly",
            "other_credit_card_limits",
            "rent_or_board_monthly",
            # Living situation
            "housing_situation",
            "time_at_current_address_years",
            "number_of_dependants",
            "previous_suburb",
            "previous_state",
            "previous_postcode",
            # Contact
            "preferred_contact_method",
            # Computed (read-only)
            "total_assets",
            "total_monthly_liabilities",
            # Banking
            "account_tenure_years",
            "loyalty_tier",
            "num_products",
            "savings_balance",
            "checking_balance",
            "has_credit_card",
            "has_mortgage",
            "has_auto_loan",
            "on_time_payment_pct",
            "previous_loans_repaid",
            # Timestamps
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "total_assets",
            "total_monthly_liabilities",
            "created_at",
            "updated_at",
            # Banking fields — managed by the bank, not editable via profile endpoint
            "account_tenure_years",
            "loyalty_tier",
            "num_products",
            "savings_balance",
            "checking_balance",
            "has_credit_card",
            "has_mortgage",
            "has_auto_loan",
            "on_time_payment_pct",
            "previous_loans_repaid",
        )
        extra_kwargs = {
            "primary_id_number": {"write_only": True, "required": False},
            "secondary_id_number": {"write_only": True, "required": False},
        }

    def get_primary_id_number_masked(self, obj):
        return _mask_id_number(obj.primary_id_number)

    def get_secondary_id_number_masked(self, obj):
        return _mask_id_number(obj.secondary_id_number)

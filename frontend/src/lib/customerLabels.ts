/**
 * Shared customer-choice label maps.
 *
 * Backend `TextChoices` enums (CustomerProfile.ResidencyStatus, IdType,
 * MaritalStatus, EmploymentStatus, HousingSituation, Industry,
 * ContactMethod, Tier) return wire-format values. These maps turn those
 * values into display strings and tier-color tokens.
 *
 * Used by /dashboard/customers/[id] and /dashboard/profile. Mirror any
 * backend TextChoices additions here.
 */

export const tierColors: Record<string, string> = {
  standard: 'bg-gray-100 text-gray-800',
  silver: 'bg-slate-200 text-slate-800',
  gold: 'bg-yellow-100 text-yellow-800',
  platinum: 'bg-purple-100 text-purple-800',
}

export const residencyLabels: Record<string, string> = {
  citizen: 'Australian Citizen',
  permanent_resident: 'Permanent Resident',
  temporary_visa: 'Temporary Visa Holder',
  nz_citizen: 'New Zealand Citizen',
}

export const idTypeLabels: Record<string, string> = {
  drivers_licence: "Driver's Licence",
  passport: 'Australian Passport',
  medicare: 'Medicare Card',
  immicard: 'ImmiCard',
}

export const maritalLabels: Record<string, string> = {
  single: 'Single',
  married: 'Married',
  de_facto: 'De Facto',
  divorced: 'Divorced',
  widowed: 'Widowed',
}

export const employmentStatusLabels: Record<string, string> = {
  payg_permanent: 'PAYG Permanent',
  payg_casual: 'PAYG Casual',
  self_employed: 'Self Employed',
  contract: 'Contract',
  retired: 'Retired',
  unemployed: 'Unemployed',
  home_duties: 'Home Duties',
}

export const housingSituationLabels: Record<string, string> = {
  own_outright: 'Own Outright',
  mortgage: 'Mortgage',
  renting: 'Renting',
  boarding: 'Boarding',
  living_with_parents: 'Living with Parents',
}

export const industryLabels: Record<string, string> = {
  agriculture: 'Agriculture',
  mining: 'Mining',
  manufacturing: 'Manufacturing',
  utilities: 'Utilities',
  construction: 'Construction',
  wholesale_trade: 'Wholesale Trade',
  retail_trade: 'Retail Trade',
  accommodation_food: 'Accommodation & Food',
  transport_postal: 'Transport & Postal',
  information_media: 'Information & Media',
  financial_insurance: 'Financial & Insurance',
  property_services: 'Property Services',
  professional_scientific: 'Professional & Scientific',
  administrative: 'Administrative',
  public_admin: 'Public Administration',
  education_training: 'Education & Training',
  healthcare_social: 'Healthcare & Social',
  arts_recreation: 'Arts & Recreation',
  other_services: 'Other Services',
}

export const contactMethodLabels: Record<string, string> = {
  email: 'Email',
  phone: 'Phone',
  sms: 'SMS',
}

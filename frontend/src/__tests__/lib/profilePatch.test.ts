import { buildProfilePatch } from '@/lib/profilePatch'

describe('buildProfilePatch', () => {
  it('sends null for a cleared field the server stores as nullable', () => {
    expect(buildProfilePatch<Record<string, unknown>>({ years_in_current_role: 3 }, { years_in_current_role: '' })).toEqual({
      years_in_current_role: null,
    })
  })

  it('sends 0 for a cleared field the server stores as NOT NULL with a zero default', () => {
    // estimated_property_value is DecimalField(default=0) with no null=True: null is a 400.
    expect(buildProfilePatch<Record<string, unknown>>({ estimated_property_value: 650000 }, { estimated_property_value: '' })).toEqual({
      estimated_property_value: 0,
    })
  })

  it('leaves out fields that did not change', () => {
    expect(buildProfilePatch<Record<string, unknown>>({ phone: '0400', savings_balance: 10 }, { phone: '0411', savings_balance: 10 })).toEqual({
      phone: '0411',
    })
  })
})

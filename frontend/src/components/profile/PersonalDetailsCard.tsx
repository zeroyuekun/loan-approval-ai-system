import type { ChangeEvent } from 'react'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectItem } from '@/components/ui/select'
import { UserCircle } from 'lucide-react'
import { AU_STATES } from '@/lib/customerLabels'
import type { CustomerProfile, User } from '@/types'

interface PersonalDetailsCardProps {
  user: User | null
  form: Partial<CustomerProfile>
  onChange: (e: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => void
}

/** Editable personal details + residential address, shared by both customer profile pages. */
export function PersonalDetailsCard({ user, form, onChange: handleChange }: PersonalDetailsCardProps) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <UserCircle className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">Personal Details</CardTitle>
        </div>
        <CardDescription>Required under the National Consumer Credit Protection Act 2009 (NCCP) for responsible lending assessment.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Full Name</Label>
            <Input value={`${user?.first_name || ''} ${user?.last_name || ''}`} disabled />
          </div>
          <div>
            <Label>Email</Label>
            <Input value={user?.email || ''} disabled />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label htmlFor="date_of_birth">Date of Birth</Label>
            <Input id="date_of_birth" name="date_of_birth" type="date" value={(form.date_of_birth as string) || ''} onChange={handleChange} />
          </div>
          <div>
            <Label htmlFor="phone">Phone Number</Label>
            <Input id="phone" name="phone" value={(form.phone as string) || ''} onChange={handleChange} placeholder="04XX XXX XXX" />
          </div>
        </div>
        <div>
          <Label htmlFor="marital_status">Marital Status</Label>
          <Select id="marital_status" name="marital_status" value={(form.marital_status as string) || ''} onChange={handleChange}>
            <SelectItem value="">Select...</SelectItem>
            <SelectItem value="single">Single</SelectItem>
            <SelectItem value="married">Married</SelectItem>
            <SelectItem value="de_facto">De Facto</SelectItem>
            <SelectItem value="divorced">Divorced</SelectItem>
            <SelectItem value="widowed">Widowed</SelectItem>
          </Select>
        </div>

        <div className="pt-2">
          <Label className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Residential Address</Label>
        </div>
        <div>
          <Label htmlFor="address_line_1">Street Address</Label>
          <Input id="address_line_1" name="address_line_1" value={(form.address_line_1 as string) || ''} onChange={handleChange} placeholder="123 Example Street" />
        </div>
        <div>
          <Label htmlFor="address_line_2">Address Line 2</Label>
          <Input id="address_line_2" name="address_line_2" value={(form.address_line_2 as string) || ''} onChange={handleChange} placeholder="Unit/Apartment (optional)" />
        </div>
        <div className="grid grid-cols-3 gap-4">
          <div>
            <Label htmlFor="suburb">Suburb</Label>
            <Input id="suburb" name="suburb" value={(form.suburb as string) || ''} onChange={handleChange} placeholder="Sydney" />
          </div>
          <div>
            <Label htmlFor="state">State</Label>
            <Select id="state" name="state" value={(form.state as string) || ''} onChange={handleChange}>
              <SelectItem value="">Select...</SelectItem>
              {AU_STATES.map((s) => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="postcode">Postcode</Label>
            <Input id="postcode" name="postcode" value={(form.postcode as string) || ''} onChange={handleChange} placeholder="2000" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

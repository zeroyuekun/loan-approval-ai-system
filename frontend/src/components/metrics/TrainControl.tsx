'use client'

import { Button } from '@/components/ui/button'
import { Select, SelectItem } from '@/components/ui/select'
import { Loader2 } from 'lucide-react'

interface TrainControlProps {
  selectedAlgorithm: string
  onSelect: (value: string) => void
  onTrain: () => void
  isTraining: boolean
  label: string
}

export function TrainControl({ selectedAlgorithm, onSelect, onTrain, isTraining, label }: TrainControlProps) {
  return (
    <div className="flex items-center gap-2">
      <Select value={selectedAlgorithm} onChange={(e) => onSelect(e.target.value)}>
        <SelectItem value="xgb">XGBoost</SelectItem>
        <SelectItem value="rf">Random Forest</SelectItem>
      </Select>
      <Button onClick={onTrain} disabled={isTraining}>
        {isTraining ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
        {isTraining ? 'Training...' : label}
      </Button>
    </div>
  )
}

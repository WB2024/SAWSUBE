import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import TVControl from './TVControl'
vi.mock('../components/Toast', () => ({ useToast: () => ({ push: vi.fn() }) }))
vi.mock('../lib/api', () => ({ api: {
  get: vi.fn(async (path: string) => {
    if (path === '/api/tvs') return [{ id: 1, name: 'The Frame 32', ip: '192.168.1.4' }]
    if (path.endsWith('/mattes')) return [{ matte_type: 'none' }, { matte_type: 'modern' }]
    if (path.endsWith('/settings')) return { brightness: 2, color_temp: 1 }
    if (path.endsWith('/status')) return { online: true, paired: true }
    if (path.startsWith('/api/images')) return []
    return {}
  }), post: vi.fn(), del: vi.fn()
} }))
describe('TV Control with Frame 32 API responses', () => {
  it('keeps rendering when matte entries are objects and shows current numeric settings', async () => {
    render(<TVControl />)
    await waitFor(() => expect(screen.getByText('Mattes available (2)')).toBeInTheDocument())
    expect(screen.getByText('modern')).toBeInTheDocument()
    expect(screen.getByLabelText('Brightness (1–10)')).toHaveValue(2)
    expect(screen.getByLabelText('Color temp (-5..5)')).toHaveValue(1)
  })
})

import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import Sources from './Sources'
import { api } from '../lib/api'

const push = vi.fn()
vi.mock('../components/Toast', () => ({ useToast: () => ({ push }) }))
vi.mock('../lib/api', () => ({ api: { get: vi.fn(), post: vi.fn(), del: vi.fn() } }))

describe('Sources — The Met tab', () => {
  beforeEach(() => { vi.mocked(api.get).mockReset(); vi.mocked(api.post).mockReset(); push.mockReset() })

  it('keeps Unsplash as the default tab', () => {
    render(<Sources />)
    expect(screen.queryByLabelText('Search The Met')).not.toBeInTheDocument()
  })

  it('searches and imports a painting', async () => {
    vi.mocked(api.get).mockResolvedValue([{ id: '437853', title: 'Whalers', credit: 'Turner', thumb: 't.jpg' }])
    vi.mocked(api.post).mockResolvedValue({})
    render(<Sources />)
    fireEvent.click(screen.getByRole('button', { name: 'The Met' }))
    fireEvent.change(screen.getByLabelText('Search The Met'), { target: { value: 'turner' } })
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(screen.getByText('Whalers')).toBeInTheDocument())
    expect(api.get).toHaveBeenCalledWith('/api/sources/met/search?q=turner')
    fireEvent.click(screen.getByRole('button', { name: 'Import' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/api/sources/met/import', { id: '437853' }))
    expect(push).toHaveBeenCalledWith({ type: 'success', text: 'Imported Whalers to Library' })
  })

  it('shows an empty state when nothing matches', async () => {
    vi.mocked(api.get).mockResolvedValue([])
    render(<Sources />)
    fireEvent.click(screen.getByRole('button', { name: 'The Met' }))
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(screen.getByText('No public-domain paintings found.')).toBeInTheDocument())
  })

  it('reports API errors', async () => {
    vi.mocked(api.get).mockRejectedValue(new Error('The Met collection API is unavailable'))
    render(<Sources />)
    fireEvent.click(screen.getByRole('button', { name: 'The Met' }))
    fireEvent.click(screen.getByRole('button', { name: 'Search' }))
    await waitFor(() => expect(push).toHaveBeenCalledWith({ type: 'error', text: 'The Met collection API is unavailable' }))
  })
})

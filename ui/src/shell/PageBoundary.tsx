import { Component, type ReactNode } from 'react'
import { ErrorState } from '../components/ErrorState'

/** A page that fails while it is being drawn must not take the whole interface with it: the
 *  rail and the search bar stay, and the officer is told what to do. It resets when the
 *  address changes (`resetKey`), so leaving the page is enough to carry on. */
export class PageBoundary extends Component<{ resetKey: string; children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidUpdate(prev: { resetKey: string }) {
    if (prev.resetKey !== this.props.resetKey && this.state.failed) this.setState({ failed: false })
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <ErrorState
        title="This page could not be shown"
        detail="Something in it could not be drawn. Nothing was changed or lost. Try again; if it keeps happening, open the case from the list of cases, or trace the wallet again."
        onRetry={() => this.setState({ failed: false })}
      />
    )
  }
}

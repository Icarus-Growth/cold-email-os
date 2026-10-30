/* One screen failing to draw must not take the whole app down with it. */
import React from 'react';
import { Notice } from '../ui';

export class AreaBoundary extends React.Component<{ name: string; children: React.ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error) { console.error('[os] ' + this.props.name + ' failed to draw:', error); }
  render() {
    if (this.state.error) {
      return <Notice tone="bad" title={this.props.name + ' could not be shown'}>{String(this.state.error.message || this.state.error)}</Notice>;
    }
    return this.props.children;
  }
}

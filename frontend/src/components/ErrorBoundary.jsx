import { Component } from "react";

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(err) {
    return { error: err };
  }

  componentDidCatch(err, info) {
    console.error("[ErrorBoundary]", err, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div style={{
          padding: "20px", color: "#f87171",
          background: "#1e1e2e", minHeight: "100vh",
          fontFamily: "monospace", whiteSpace: "pre-wrap",
        }}>
          <h2>⚠️ 發生錯誤</h2>
          <p>{String(this.state.error)}</p>
          <p style={{ color: "#94a3b8", fontSize: "12px" }}>
            {this.state.error?.stack}
          </p>
          <button
            style={{ marginTop: "16px", padding: "8px 16px", cursor: "pointer" }}
            onClick={() => this.setState({ error: null })}
          >
            重試
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

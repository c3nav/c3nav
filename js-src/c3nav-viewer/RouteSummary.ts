export class RouteSummary {
    root;

    origin = null;
    destination = null;

    constructor(root) {
        this.root = root;

        on(this.root, 'click', '.options', this.onOptionsClick);
    }

    onOptionsClick = e => {
        c3nav.update_state_new({options: !c3nav.state.options});
    }

    setLoading = (loading) => {
        this.root.classList.toggle('loading', loading);
    }

    isLoading = () => {
        return this.root.classList.contains('loading');
    }

    setError = (error) => {
        this.root.querySelector('span').textContent = error;
        this.setLoading(false);
    }

    setSummary(summary, options_summary) {
        this.root.querySelector('span').textContent = summary;
        this.root.querySelector('em').textContent = options_summary;
        this.setLoading(false);
    }

}
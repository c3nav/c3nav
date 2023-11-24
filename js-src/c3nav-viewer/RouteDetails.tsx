export class RouteDetails {
    root: HTMLElement;
    report: HTMLLinkElement;
    body: HTMLElement;

    constructor(root: HTMLElement) {
        this.root = root;
        this.report = root.querySelector('.report');
        this.body = root.querySelector('.details-body');

        on(root, 'click', '.close', this.close);
    }

    setIssueUrl(url: string) {
        this.report.href = url;
    }


    setLoading = (loading: boolean) => {
        this.root.classList.toggle('loading', loading);
    }

    setRoute(route: Route) {
        this.body.replaceChildren();
        this.body.append(c3nav._build_location_html(route.origin));
        for (const item of route.items) {
            for (const [icon, text] of item.descriptions) {
                this.body.append(<div className="routeitem">
                    {icon.indexOf('.') === -1
                        ? <span className="icon"><i className="material-icons">{icon}</i></span>
                        : <span className="icon"><img src={`/static/site/img/icons/${icon}`}/></span>}
                    <span>{text}</span>
                </div>);
            }
        }
        this.body.append(c3nav._build_location_html(route.destination));
        this.setLoading(false);
    }

    close = () => {
        c3nav.update_state_new({details: false});
    }
}
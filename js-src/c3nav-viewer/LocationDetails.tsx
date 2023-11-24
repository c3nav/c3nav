import {Api2} from "../api/api2";

export class LocationDetails {
    root: HTMLElement;
    detailsBody: HTMLElement;
    editor: HTMLLinkElement;
    reportIssue: HTMLLinkElement;
    reportMissing: HTMLLinkElement;

    id: number = null;

    constructor(root: HTMLElement, private api: Api2) {
        this.root = root;
        this.detailsBody = this.root.querySelector('.details-body')
        this.editor = this.root.querySelector('.editor')
        this.reportIssue = this.root.querySelector('.report-issue');
        this.reportMissing = this.root.querySelector('.report-missing');

        on(root, 'click', '.close', this.close);
    }

    close = () => {
        c3nav.update_state_new({details: false});
    }


    async load(location: C3NavLocation) {
        if (this.id !== location.id) {
            this.setLoading(true);
            this.id = location.id;
            c3nav._clear_route_layers();
            try {
                const data = await this.api.map.mapLocationByIdDisplay({
                    locationId: location.id,
                });
                if (this.id !== data.id) {
                    return;
                }
                this.setLocation(data);
                if (data.geometry && data.level) {
                    L.geoJSON(data.geometry, {
                        style: {
                            color: c3nav._primary_color,
                            fillOpacity: 0.1,
                        }
                    }).addTo(c3nav._routeLayers[data.level as string]);
                }
            } catch (e) {
                this.setError(e.message);
            }
        }
    }


    setLoading = (loading: boolean) => {
        this.root.classList.toggle('loading', loading);
    }

    setError = (error: string) => {
        this.detailsBody.textContent = `Error ${error}`;
        this.editor.classList.add('hidden');
        this.reportIssue.classList.add('hidden');
        this.reportMissing.classList.add('hidden');
        this.setLoading(false);
    }

    setLocation = (location: LocationDisplay) => {
        const dl = <dl/>;
        const clickhandler = id => e => {
            e.preventDefault();
            c3nav.sidebar.destination.set(c3nav.locations_by_id[id]);
            c3nav.update_state_new({details: true});
        }
        for (const line of location.display) {
            dl.append(<dt>{line[0]}</dt>);
            if (typeof line[1] === 'string') {
                dl.append(<dd>{line[1]}</dd>);
            } else if (line[1] === null || line.length === 0) {
                dl.append(<dd>-</dd>);
            } else {
                const sublocations = (line[1].length === undefined) ? [line[1]] : line[1];
                let content;
                for (const loc of sublocations) {
                    if (loc.can_search) {
                        content = <a href={`/l/${loc.slug}/details/`}
                                     onClick={clickhandler(loc.id)}>{loc.title}</a>;
                    } else {
                        content = <span>{loc.title}</span>;
                    }
                }
                dl.append(<dd>{content}</dd>);
            }
        }
        this.detailsBody.replaceChildren(dl);

        if (location.editor_url) {
            this.editor.href = location.editor_url as string;
            this.editor.classList.remove('hidden');
        } else {
            this.editor.classList.add('hidden');
        }

        if (location.geometry) {
            if (typeof location.id === 'number') {
                this.reportMissing.classList.add('hidden');
                this.reportIssue.classList.remove('hidden');
                this.reportIssue.href = `/report/l/${location.id}/`;
            } else {
                this.reportIssue.classList.add('hidden');
                this.reportMissing.classList.remove('hidden');
                this.reportMissing.href = `/report/l/${location.id}/`;
            }
        } else {
            this.reportIssue.classList.add('hidden');
            this.reportMissing.classList.add('hidden');
        }
        this.setLoading(false);
    }

}
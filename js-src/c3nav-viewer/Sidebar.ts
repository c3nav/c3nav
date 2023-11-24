import {RouteSummary} from "./routeSummary";
import {AutoComplete} from "./autoComplete";
import {LocationDetails} from "./locationDetails";
import {RouteDetails} from "./routeDetails";
import {RouteOptions} from "./routeOptions";

export class Sidebar {
    root;
    search;
    resultswrapper;
    origin;
    destination;
    autocomplete;
    locationDetails;
    routeDetails;
    routeOptions;
    locationButtons;
    routeSummary;
    routeSearchButtons;
    routeResultButtons;

    constructor(root) {
        this.root = root;
        this.search = root.querySelector('#search');
        this.resultswrapper = root.querySelector('#resultswrapper');
        this.locationButtons = root.querySelector('#location-buttons');
        this.routeSummary = new RouteSummary(root.querySelector('#route-summary'));
        this.routeSearchButtons = root.querySelector('#route-search-buttons');
        this.routeResultButtons = root.querySelector('#route-result-buttons');

        this.origin = new OriginInput(root.querySelector('#origin-input'));
        this.destination = new DestinationInput(root.querySelector('#destination-input'));
        this.autocomplete = new AutoComplete(root.querySelector('#autocomplete'));
        this.locationDetails = new LocationDetails(root.querySelector('#location-details'));
        this.routeDetails = new RouteDetails(root.querySelector('#route-details'));
        this.routeOptions = new RouteOptions(root.querySelector('#route-options'));


        on([this.locationButtons, this.routeResultButtons], 'click', '.details', this.onDetailsClick);
        on(this.locationButtons, 'click', '.share', this.onShareClick);
        on(this.locationButtons, 'click', '.route', this.onRouteClick);
        on([this.routeSearchButtons, this.routeResultButtons], 'click', '.swap', this.onSwapClick);
        on(this.routeSearchButtons, 'click', '.close', this.onCloseClick);
    }

    onDetailsClick = e => {
        c3nav.update_state_new({details: !c3nav.state.details});
    }

    onShareClick = e => {
        c3nav.modal.open(document.querySelector('main > .share-ui').outerHTML);
        c3nav._update_share_ui(false, location);
    }

    onRouteClick = e => {
        c3nav.update_state_new({routing: true});
    }

    onSwapClick = e => {
        const tmp = this.origin.location;
        this.origin.set(this.destination.location);
        this.destination.set(tmp);

        const offset = this.destination.root.getBoundingClientRect().top - this.origin.root.getBoundingClientRect().top;
        this.origin.root.style.transition = '';
        this.destination.root.style.transition = '';
        this.origin.root.style.top = `${offset}px`;
        this.destination.root.style.top = `-${offset}px`;
        window.setTimeout(() => {
            this.origin.root.style.transition = `top 150ms`;
            this.destination.root.style.transition = `top 150ms`;
            this.origin.root.style.top = 0;
            this.destination.root.style.top = 0;
        }, 0);
        c3nav.update_state_new();
    }

    onCloseClick = e => {
        if (this.origin.isSelected() && !this.destination.isSelected()) {
            this.destination.set(this.origin.location);
        }
        c3nav.update_state_new({routing: false});
    }

    unfocusSearch = () => {
        this.search.classList.remove('focused');
    }

    focusSearch = () => {
        this.search.classList.add('focused');
    }


}
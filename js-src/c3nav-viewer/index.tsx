import {Settings} from './Settings'
import {Sidebar} from "./Sidebar";
import {Modal} from "./Modal";
import {Messages} from "./Messages";
import {Api} from "../api/api";

class C3Nav {
    public readonly settings: Settings;
    public readonly sidebar: Sidebar;
    public readonly modal: Modal;
    public readonly messages: Messages;
    private api: Api;
    constructor() {
        this.api = new Api('');
        this.api.authorize_session().then(() => {
            this.load_searchable_locations();
        })

        this.settings = new Settings(localStorage);
        this.sidebar = new Sidebar(document.querySelector('#sidebar'));
        this.modal = new Modal(document.querySelector('#modal'));
        this.messages = new Messages(document.querySelector('#messages'));


    }

    private async load_searchable_locations() {
        this.searchable_locations_timer = null;
        const data = await this.api.map.mapLocationList({
            searchable: true,
        });

    }
}

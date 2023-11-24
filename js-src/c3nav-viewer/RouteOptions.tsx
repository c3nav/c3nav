export class RouteOptions {
    root;
    fields;

    constructor(root) {
        this.root = root;
        this.fields = root.querySelector('.route-options-fields');

        on(this.root, 'click', '.close', this.close);
        on(this.root, 'click', 'button', this.submit);
    }

    close = () => {
        c3nav.update_state_new({options: false});
    }

    submit = (e, el) => {
        const options = {};
        for (const field of this.root.querySelectorAll('.route-options-fields [name]')) {
            options[field.name] = field.value;
        }
        if (el.matches('.save')) {
            c3nav.json_post('/api/routing/options/', options)
        }
        c3nav.next_route_options = options;
        c3nav.update_state_new({options: false});
    }

    setLoading = (loading) => {
        this.root.classList.toggle('loading', loading);
    }

    setOptions = (options) => {
        this.fields.replaceChildren();
        for (const option of options) {
            const field_id = `option_id_${option.name}`;
            this.fields.append(<label htmlFor={field_id}>{option.label}</label>);
            let field;
            if (option.type === 'select') {
                field = <select name={option.name} id={field_id} value={option.value}>
                    {option.choices.map(choice => <option value={choice.name}>{choice.title}</option>)}
                </select>
            }
            this.fields.append(field);
        }
        this.setLoading(false);
    }
}
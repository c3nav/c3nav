import {OriginInput} from "./OriginInput";

export class DestinationInput extends OriginInput {
    randomButton: HTMLElement;

    constructor(root: HTMLElement) {
        super(root);
        this.randomButton = root.querySelector('button.random');

        on(this.randomButton, 'click', this.onRandomClick);
    }


    onRandomClick = async (e: MouseEvent) => {
        try {
            const {width, height} = this.root.getBoundingClientRect();
            const buttonRect = this.randomButton.getBoundingClientRect();
            const left = buttonRect.left + buttonRect.width / 2;
            const cover = <div style={{
                width: `${width}px`,
                height: `${height}px`,
                left: `${left}px`,
            }}></div>;
            this.root.append(cover);
            const new_left = 5 + buttonRect.width / 2;
            this.randomButton.style.left = `${buttonRect.left}px`;
            this.randomButton.classList.add('animating');
            await nextTick();
            cover.style.left = `${new_left}px`;
            this.randomButton.style.left = `5px`;
            await nextTick();
            const transitionEndAwaiter = waitEvent([cover, this.randomButton], 'transitionend', 350);
            const location = c3nav.choose_random_location();
            await transitionEndAwaiter;
            c3nav.sidebar.destination.set(location);
            c3nav.update_state(false);
            c3nav.fly_to_bounds(true);
            cover.style.left = `${width + buttonRect.width / 2}px`;
            this.randomButton.style.left = `${width}px`;
            await waitEvent([cover, this.randomButton], 'transitionend', 350);
            this.randomButton.classList.add('hidden');
            this.randomButton.classList.remove('animating');
            cover.remove();
            this.randomButton.style.removeProperty('left');
            await wait(100)
            this.randomButton.classList.remove('hidden');
        } catch (e) {
            console.log(e);
        }
    }
}

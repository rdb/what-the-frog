import pyglet
from pyglet import gl
import pyglet.sprite
import pyglet.resource
from pymunk.vec2d import Vec2d
import moderngl
from pyrr import Matrix44
import pymunk.pyglet_util

from . import PIXEL_SCALE
import wtf.keys
from .directions import Direction
from .physics import (
    space, COLLISION_TYPE_FROG, COLLISION_TYPE_COLLECTIBLE, create_walls
)
from .state import LevelState, UnderwaterState
from .water import Water, WaterBatch
from .geom import SPACE_SCALE
from .actors import actor_sprites, Frog, Fly
from .hud import HUD
from .offscreen import OffscreenBuffer
from .poly import RockPoly
from .level_loader import load_level, NoSuchLevel
from .screenshot import take_screenshot
from . import sounds


SCREENSHOTS = True
START_LEVEL = "easy1"
LEVEL_SETS = [
    "easy",
    "level",
    "hard",
]


WIDTH = 1600   # Width in hidpi pixels
HEIGHT = 1200  # Height in hidpi pixels


slowmo = False

window = pyglet.window.Window(
    width=round(WIDTH * PIXEL_SCALE),
    height=round(HEIGHT * PIXEL_SCALE)
)


mgl = moderngl.create_context()


def water(y, x1=0, x2=WIDTH * SPACE_SCALE, bot_y=0):
    return Water(y, x1, x2, bot_y)


def on_collect(arbiter, space, data):
    """Called when a collectible is hit"""
    fly, frog = arbiter.shapes
    frog.obj.lick(fly.obj.sprite.position)
    fly.obj.collect(frog, controls)
    space.remove(fly)
    level.actors.remove(fly.obj)
    if not Fly.insts:
        pyglet.clock.schedule_once(level.win, 0.8)

    sounds.play('lick')
    return False


handler = space.add_collision_handler(
    COLLISION_TYPE_COLLECTIBLE,
    COLLISION_TYPE_FROG
)
handler.begin = on_collect


def on_hit(arbiter, space, data):
    # Play a splatty sound
    frog, other = arbiter.shapes
    body = frog.body
    if not body:
        return True

    v2 = body.velocity.get_length_sqrd()
    vol = min(1.0, v2 / 1300)
    if vol > 0.1:
        sounds.play('splat', volume=vol)
    return True


handler = space.add_collision_handler(
    COLLISION_TYPE_FROG, 0
)
handler.begin = on_hit


class Level:
    def __init__(self, name=None):
        self.state = LevelState.PLAYING
        self.pc = None
        self.objs = []
        self.actors = []
        self.static_shapes = []

        self.background = pyglet.sprite.Sprite(
            pyglet.resource.image('backgrounds/default.jpg')
        )
        self.fg_batch = pyglet.graphics.Batch()
        if name:
            self.load(name)

    def load(self, level_name):
        """Load the given level name."""
        self.name = level_name
        self.reload()
        if SCREENSHOTS:
            pyglet.clock.schedule_once(
                lambda dt: take_screenshot(
                    window,
                    f'assets/levelpics/{level_name}.png'
                ),
                0.3
            )

    def next_level(self):
        """Progress to the next level."""
        stem = self.name.rstrip('0123456789')
        digit = int(self.name[len(stem):])
        digit += 1
        try:
            self.load(f"{stem}{digit}")
        except NoSuchLevel:
            idx = LEVEL_SETS.index(stem)
            if idx + 1 == len(LEVEL_SETS):
                # TODO: show "You win" card
                return
            stem = LEVEL_SETS[idx + 1]
            self.load(f"{stem}1")

    @property
    def won(self):
        if self.state == LevelState.PLAYING:
            return None

        return self.state.value > 2

    def win(self, *_):
        if self.state is not LevelState.PLAYING:
            return
        self.state = LevelState.PERFECT
        hud.show_card('3star')

    def fail(self, *_):
        if self.state is not LevelState.PLAYING:
            return

        flies_remaining = len(Fly.insts)
        if flies_remaining == 1:
            hud.show_card('2star')
            self.state = LevelState.WON
        elif flies_remaining == 2:
            hud.show_card('1star')
            self.state = LevelState.WON
        else:
            self.state = LevelState.FAILED
            hud.show_card('fail')

    def create(self):
        self.state = LevelState.PLAYING
        self.pc = None
        self.objs = []
        self.actors = []
        self.static_shapes = create_walls(space, WIDTH, HEIGHT)
        self.set_background(self.name)
        load_level(self)
        if self.pc is None:
            self.pc = Frog(6, 7)
        controls.reset()
        controls.pc = self.pc

    def set_background(self, name):
        try:
            img = pyglet.resource.image(f'backgrounds/{name}.jpg')
        except pyglet.resource.ResourceNotFoundException:
            img = pyglet.resource.image('backgrounds/default.jpg')
        self.background.image = img

    def reload(self):
        self.delete()
        self.create()

    def delete(self):
        for o in self.objs:
            try:
                o.delete()
            except KeyError:
                raise KeyError(f"Couldn't delete {o}")
        for a in self.actors:
            a.delete()
        for w in Water.insts[:]:
            w.delete()
        self.pc = None
        space.remove(*self.static_shapes)
        self.static_shapes = []
        self.actors = []
        self.objs = []
        self.fg_batch = pyglet.graphics.Batch()
        assert not space.bodies, f"Space contains bodies: {space.bodies}"
        assert not space.shapes, f"Space contains shapes: {space.shapes}"


fps_display = pyglet.clock.ClockDisplay()


offscreen = OffscreenBuffer(WIDTH, HEIGHT, mgl)


water_batch = WaterBatch(mgl)

level = Level()

pymunk_drawoptions = pymunk.pyglet_util.DrawOptions()


def on_draw(dt):
    if slowmo:
        dt *= 1 / 3

    # Update graphical things
    for a in level.actors:
        a.update(dt)

    for w in Water.insts:
        w.update(dt)

    hud.update(dt)

    window.clear()

    with offscreen.bind_buffer() as fbuf:
        fbuf.clear(0.13, 0.1, 0.1)
        gl.glLoadIdentity()
        gl.glScalef(PIXEL_SCALE, PIXEL_SCALE, 1)
        level.background.draw()
        RockPoly.batch.draw()
        actor_sprites.draw()
        level.fg_batch.draw()

    mgl.screen.clear()
    offscreen.draw()

    mvp = Matrix44.orthogonal_projection(
        0, WIDTH * SPACE_SCALE,
        0, HEIGHT * SPACE_SCALE,
        -1, 1,
        dtype='f4'
    )

    with offscreen.bind_texture():
        water_batch.render(dt, mvp)
    gl.glUseProgram(0)

    hud.draw()

#    gl.glLoadIdentity()
#    gl.glScalef(PIXEL_SCALE / SPACE_SCALE, PIXEL_SCALE / SPACE_SCALE, 1)
#    space.debug_draw(pymunk_drawoptions)

#    fps_display.draw()


class JumpController:
    """Control the frog's jumps.

    We track which jumps the frog has available.

    """
    IMPULSE_SCALE = 26
    JUMP_IMPULSES = {
        Direction.UL: Vec2d.unit().rotated_degrees(30) * IMPULSE_SCALE,
        Direction.U: Vec2d.unit() * IMPULSE_SCALE,
        Direction.UR: Vec2d.unit().rotated_degrees(-30) * IMPULSE_SCALE,
        Direction.DL: Vec2d.unit().rotated_degrees(180 - 60) * IMPULSE_SCALE,
        Direction.D: Vec2d.unit().rotated_degrees(180) * IMPULSE_SCALE,
        Direction.DR: Vec2d.unit().rotated_degrees(180 + 60) * IMPULSE_SCALE,
    }

    def __init__(self, level, hud):
        self.level = level
        self.hud = hud
        self.available = None
        self.reset()

    def reset(self):
        """Set all directions back to available."""
        if self.available and not any(self.available.values()):
            pyglet.clock.unschedule(self.level.fail)
        self.available = dict.fromkeys(Direction, True)
        for d in Direction:
            self.hud.set_available(d, True)

    def all_available(self):
        """return True if all directions are available."""
        return all(self.available.values())

    def jump(self, direction):
        """Request a jump in the given direction."""
        if self.available[direction]:
            pc = self.level.pc
            pc.body.velocity = self.JUMP_IMPULSES[direction]
            self.available[direction] = False
            self.hud.set_available(direction, False)

            is_dive = (
                pc.body.underwater == UnderwaterState.UNDERWATER
                or pc.body.underwater == UnderwaterState.SURFACE
                and 'D' in direction.name
            )
            sounds.jump(underwater=is_dive)
            if not any(self.available.values()):
                pyglet.clock.schedule_once(self.level.fail, 1.3)
        else:
            self.hud.warn_unavailable(direction)


hud = HUD(WIDTH, HEIGHT)
controls = JumpController(level, hud)

keyhandler = None


def set_keyhandler(slowmo=False):
    global keyhandler
    if keyhandler:
        window.pop_handlers()
        window.pop_handlers()

    cls = (
        wtf.keys.SlowMoKeyInputHandler if slowmo else wtf.keys.KeyInputHandler
    )
    keyhandler = cls(
        jump=controls.jump,
        window=window,
    )
    window.push_handlers(keyhandler)
    window.push_handlers(wtf.keys.RestartKeyHandler(level))


def exit():
    """Exit the game."""
    pyglet.clock.unschedule(on_draw)
    pyglet.clock.unschedule(update_physics)
    level.delete()
    pyglet.app.exit()


def update_physics(dt):
    if level.won is not None:
        return

    steps = 1 if slowmo else 3
    for _ in range(steps):
        space.step(1 / 180)


def run(level_name=None, slowmo=False):
    set_keyhandler(slowmo)
    level.load(level_name or "easy1")
    pyglet.clock.set_fps_limit(60)
    pyglet.clock.schedule(on_draw)
    pyglet.clock.schedule(update_physics)
    pyglet.app.run()

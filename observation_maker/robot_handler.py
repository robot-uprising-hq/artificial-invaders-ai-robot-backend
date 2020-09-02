import numpy as np
from Box2D import (
    b2RayCastCallback,
    b2Vec2,
    b2_pi,
    b2PolygonShape,
    b2Color)
from math import sin, cos

from utils.utils import get_ray_angles
from itertools import cycle


LOWER_TAGS = ["good_ball", "good_goal", "wall"]
UPPER_TAGS = ["empty", "good_goal", "wall"]
HIT_DISTANCE_OFFSET = 0.00


class RobotHandler(object):
    def __init__(self, world, renderer, params):
        self._world = world
        self._renderer = renderer
        vertices = [
            (40, 50),
            (40, -50),
            (-40, -50),
            (-40, 50)]
        # Create balls if needed and update their position
        self._robot1 = self._world.CreateStaticBody(
            position=(0, 0),
            shapes=b2PolygonShape(vertices=vertices))
        self._robot1.userData = {'type': 'robot1'}
        for fixture in self._robot1.fixtures:
            fixture.sensor = True

        self._raycaster = Raycaster(
            self._world,
            self._renderer,
            params)

    @property
    def angles(self):
        return self._raycaster.angles

    def get_observations(self):
        return self._lower_observations, self._upper_observations

    def set_transforms(self, robot1_transform, robot2_transform):
        if robot1_transform is None or len(robot1_transform) == 0:
            self._robot1.active = False
            self._robot1.position = b2Vec2(5000, 5000)
        else:
            self._robot1.active = True
            self._robot1.position = b2Vec2(
                robot1_transform['position'][0],
                robot1_transform['position'][1])
            self._robot1.angle = \
                -robot1_transform['rotation'][0] * b2_pi / 180

    def update(self):
        if self._robot1.active is False:
            self._lower_observations = None
            self._upper_observations = None
        else:
            self._lower_observations = self._raycaster.cast(
                self._robot1.angle,
                self._robot1.position,
                LOWER_TAGS)
            self._upper_observations = self._raycaster.cast(
                self._robot1.angle,
                self._robot1.position,
                UPPER_TAGS)


class RayCastClosestCallback(b2RayCastCallback):
    """This callback finds the closest hit"""

    def __repr__(self):
        return 'Closest hit'

    def __init__(self, **kwargs):
        b2RayCastCallback.__init__(self, **kwargs)
        self.fixture = None
        self.hit = False

    def ReportFixture(self, fixture, point, normal, fraction):
        '''
        Called for each fixture found in the query. You control how the ray
        proceeds by returning a float that indicates the fractional length of
        the ray. By returning 0, you set the ray length to zero. By returning
        the current fraction, you proceed to find the closest point. By
        returning 1, you continue with the original ray clipping. By returning
        -1, you will filter out the current fixture (the ray will not hit it).
        '''
        self.hit = True
        self.fixture = fixture
        self.point = b2Vec2(point)
        self.normal = b2Vec2(normal)
        self.fraction = fraction - HIT_DISTANCE_OFFSET
        # NOTE: You will get this error:
        #   "TypeError: Swig director type mismatch in output value of
        #    type 'float32'"
        # without returning a value
        return fraction


class Raycaster():
    def __init__(self, world, renderer, params):
        self._params = params
        self.p1_color = b2Color(0.4, 0.9, 0.4)
        # self.s1_color = b2Color(0.8, 0.8, 0.8)
        # self.s2_color = b2Color(0.9, 0.9, 0.4)
        self._line_colors = [
            b2Color(0.0, 0.0, 1.0),
            b2Color(0.0, 1.0, 0.0),
            b2Color(1.0, 0.0, 0.0)
        ]
        self._front_line_color = b2Color(0.0, 1.0, 1.0)
        self.world = world
        self.renderer = renderer

        self.ray_angles = get_ray_angles(
            2 * b2_pi / 360 * params["image_processing"]["max_angle_per_side"],
            self._params["image_processing"]["number_of_rays_per_side"])

    @property
    def angles(self):
        return self.ray_angles

    def get_ray_properties(self, angle, line_color_picker):
        cast_length = self._params["image_processing"]["ray_length"]
        # For front ray use different values
        if angle == 0:
            line_color = self._front_line_color
            cast_width = self._params["image_processing"]["front_ray_width"]
        else:
            line_color = next(line_color_picker)
            cast_width = self._params["image_processing"]["ray_width"]
        return line_color, cast_length, cast_width

    def cast(self, car_angle, robot_position, tags):
        line_color_picker = cycle(self._line_colors)
        results = []
        for angle in self.ray_angles:
            (line_color,
             cast_length,
             cast_width) = self.get_ray_properties(angle, line_color_picker)

            result = self.cast_single(car_angle + angle + b2_pi / 2,
                                      robot_position,
                                      line_color,
                                      cast_length,
                                      cast_width)
            results.append(result)

        single_obs_len = len(tags) + 2
        all_obs_len = len(self.ray_angles) * single_obs_len
        all_obs = np.zeros((all_obs_len,), dtype=np.float32)
        for ray_index, hit_result in enumerate(results):
            single_obs = np.zeros((single_obs_len,), dtype=np.float32)

            if hit_result[0] is not None:
                try:
                    tag_index = tags.index(hit_result[0])
                    single_obs[tag_index] = 1.0
                    single_obs[single_obs_len - 1] = hit_result[1]
                except ValueError:
                    single_obs[single_obs_len - 2] = 1.0
            else:
                single_obs[single_obs_len - 2] = 1.0

            all_obs[
                ray_index * single_obs_len:
                (ray_index + 1) * single_obs_len] = single_obs

        return all_obs

    def cast_single(
            self,
            car_angle,
            robot_position,
            line_color,
            cast_length,
            cast_width):
        """
        Casts a single ray which technically is 3 prependicular rays.
        """
        diff_angle = b2_pi / 2
        rays = []

        # Middle ray
        start0 = robot_position
        d = (cast_length * cos(car_angle), cast_length * sin(car_angle))
        end0 = start0 + d
        rays.append([start0, end0])

        # Left ray
        diff1 = (
            cast_width * cos(car_angle - diff_angle),
            cast_width * sin(car_angle - diff_angle))
        start1 = robot_position + diff1
        end1 = start1 + d
        rays.append([start1, end1])

        # Right ray
        diff2 = (
            cast_width * cos(car_angle + diff_angle),
            cast_width * sin(car_angle + diff_angle))
        start2 = robot_position + diff2
        end2 = start2 + d
        rays.append([start2, end2])

        hits = []
        for ray in rays:
            sector_obs = np.array([0] * 5, dtype=np.float32)
            sector_obs[len(sector_obs) - 2] = 1.0

            callback = RayCastClosestCallback()

            self.world.RayCast(callback, ray[0], ray[1])

            # The callback has been called by this point, and if a
            # fixture was hit it will have been set to callback.fixture.
            point1 = self.renderer.to_screen(ray[0])
            point2 = self.renderer.to_screen(ray[1])

            if callback.hit:
                self.draw_hit(
                    point1, callback.point, callback.normal, line_color)
                hits.append(
                    {
                        "type": callback.fixture.body.userData['type'],
                        "distance": callback.fraction + 0.009
                    })
            else:
                self.renderer.DrawSegment(point1, point2, line_color)

        hit_dist = None
        hit_type = None
        for hit in hits:
            if hit_dist is None or hit["distance"] < hit_dist:
                hit_dist = hit["distance"]
                hit_type = hit["type"]

        return hit_type, hit_dist

    def draw_hit(self, start_point, cb_point, cb_normal, line_color):
        cb_point = self.renderer.to_screen(cb_point)
        head = b2Vec2(cb_point) + 0.5 * cb_normal

        cb_normal = self.renderer.to_screen(cb_normal)
        self.renderer.DrawPoint(cb_point, 5.0, self.p1_color)
        self.renderer.DrawSegment(start_point, cb_point, line_color)
        self.renderer.DrawSegment(cb_point, head, line_color)

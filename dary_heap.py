import json

class dary_heap:
    def __init__(self, d=2):
        self._n = 0         # num of nodes currently in heap
        self._d = 2         # num of children per node
        self._data = []     # array with keys
        self._location = {} # location of keys in _data

    def empty(self):
        return self._n == 0

    def get_min(self):
        if self.empty():
            raise IndexError
        else:
            return self._data[0]

    def push(self, x):
        if self._n == len(self._data):
            self._data.append(x)
        else:
            self._data[self._n] = x

        self._location[x] = self._n
        self._n += 1

        i = self._location[x]

        while i > 0:
            p = (i-1)//self._d
            if self._data[i] < self._data[p]:
                # swap
                self._data[i], self._data[p] = self._data[p], self._data[i]
                self._location[self._data[i]] = i
                self._location[self._data[p]] = p
                i = p
            else:
                break

    def pop_min(self):
        # ensure not empty
        if self.empty():
            raise IndexError

        # Erase the min
        del self._location[self._data[0]]
        self._n -= 1
        if (self._n == 0):
            return

        # Take the last element and move it to the min spot
        self._data[0] = self._data[self._n]
        self._location[self._data[0]] = 0

        # i is current node, which is min
        i = 0

        # while there is a child of current node
        while (i*self._d + 1) < self._n:
            left = i*self._d + 1
            right = (i+1)*self._d
            m = left

            # get the smallest child
            c = left+1
            while c <= right and c < self._n:
                if self._data[c] < self._data[m]:
                    m = c

                c += 1

            # if child is bigger than i, we are done
            if not (self._data[m] < self._data[i]):
                break

            # otherwise swap current with the child
            self._data[i], self._data[m] = self._data[m], self._data[i]
            self._location[self._data[i]] = i
            self._location[self._data[m]] = m

            # move current index to child index location and repeat
            i = m

    def decrease_key(self, x, newx):
        # Error if empty (no elements to perform decrease key on)
        if self.empty():
            raise IndexError

        # Update x's data with newx
        i = self._location[x]
        self._data[i] = newx
        
        # Delete x's location, replace with newx location
        del self._location[x]
        self._location[newx] = i

        # i = newx location
        # so swap up newx while i > 0 (ensuring parent exists) and newx <
        # parent
        while i > 0 and self._data[i] < self._data[(i-1)//self._d]:
            p = (i-1)//self._d
            self._data[i], self._data[p] = self._data[p], self._data[i]
            self._location[self._data[i]] = i
            self._location[self._data[p]] = p
            i = p


    # Testing function
    def is_heap(self):
        return self.__is_heap(0)

    def __is_heap(self, i):
        # left and right children
        l_index = i*self._d+1
        r_index = (i+1)*self._d

        # Test that children are larger or don't exist (if they don't exist
        # it's fine - we reached the bottom of the heap)
        missing_child = False
        
        if l_index < self._n:
            left_good = self._data[l_index] > self._data[i]
        else:
            left_good = True
            missing_child = True
            
        if r_index < self._n:
            right_good = self._data[r_index] > self._data[i]
        else:
            right_good = True
            missing_child = True

        # problem with heap detected
        if not (right_good and left_good):
            print("current: %d" % self._data[i])
            print("left: %d" % self._data[l_index])
            print("right: %d" % self._data[r_index])
            return False

        # we checked right and left are good. if one is missing, we done
        if missing_child:
            return True

        # We still have more to check
        return self.__is_heap(l_index) and self.__is_heap(r_index)

    def print_status(self):
        print("_d = %d" % self._d)
        print("_n = %d" % self._n)
        print(self._data)
        print(json.dumps(self._location, indent=4))
